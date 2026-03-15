import json

from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from messaging.models import Conversation
from survey.models import SurveySubmission

from .document_access import can_user_view_case_document, create_case_document, documents_visible_to_user_queryset
from .history_report import (
    build_case_history_report,
    resolve_customer_submission_for_history,
)
from .models import CaseDocument


def _serialize_case_document(document, request):
    file_url = ''
    try:
        if document.file:
            file_url = request.build_absolute_uri(document.file.url)
    except Exception:
        file_url = ''

    return {
        'id': document.id,
        'submission_id': document.submission_id,
        'conversation_id': document.conversation_id,
        'document_type': document.document_type,
        'document_scope': document.document_scope,
        'visibility_level': document.visibility_level,
        'uploaded_by_id': document.uploaded_by_id,
        'owner_user_id': document.owner_user_id,
        'original_filename': document.original_filename,
        'status': document.status,
        'version': document.version,
        'replaces_id': document.replaces_id,
        'metadata': document.metadata or {},
        'is_signed_final': bool(document.is_signed_final),
        'created_at': document.created_at.isoformat() if document.created_at else '',
        'updated_at': document.updated_at.isoformat() if document.updated_at else '',
        'file_url': file_url,
    }


def _absolutize_report_file_urls(report, request):
    for group in report.get('document_groups', []):
        for row in group.get('items', []):
            file_url = row.get('file_url') or ''
            if file_url and file_url.startswith('/'):
                try:
                    row['file_url'] = request.build_absolute_uri(file_url)
                except Exception:
                    pass
    return report


@require_http_methods(['GET', 'POST'])
@ensure_csrf_cookie
def api_case_documents(request):
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)

    if request.method == 'GET':
        submission_id = request.GET.get('submission_id')
        qs = documents_visible_to_user_queryset(request.user)
        if submission_id:
            try:
                submission_id_int = int(submission_id)
            except (TypeError, ValueError):
                return JsonResponse({'ok': False, 'error': '유효한 submission_id가 필요합니다.'}, status=400)
            qs = qs.filter(submission_id=submission_id_int)

        documents = list(qs.order_by('-created_at')[:200])
        return JsonResponse({'ok': True, 'documents': [_serialize_case_document(d, request) for d in documents]})

    if not (request.content_type and 'multipart/form-data' in request.content_type):
        return JsonResponse({'ok': False, 'error': 'multipart/form-data 업로드가 필요합니다.'}, status=400)

    submission_id = request.POST.get('submission_id')
    if not submission_id:
        return JsonResponse({'ok': False, 'error': 'submission_id가 필요합니다.'}, status=400)

    try:
        submission = SurveySubmission.objects.select_related('user').get(id=int(submission_id))
    except (TypeError, ValueError, SurveySubmission.DoesNotExist):
        return JsonResponse({'ok': False, 'error': '유효한 submission을 찾을 수 없습니다.'}, status=404)

    upload_file = request.FILES.get('file')
    if not upload_file:
        return JsonResponse({'ok': False, 'error': '업로드할 파일이 필요합니다.'}, status=400)

    document_type = request.POST.get('document_type') or CaseDocument.DocumentType.CUSTOMER_UPLOADED_DOCUMENT
    document_scope = request.POST.get('document_scope') or CaseDocument.DocumentScope.CASE
    visibility_level = request.POST.get('visibility_level') or CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER
    status = request.POST.get('status') or CaseDocument.Status.UPLOADED

    owner_user = None
    owner_user_id = request.POST.get('owner_user_id')
    if owner_user_id:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        owner_user = User.objects.filter(id=owner_user_id).first()

    conversation = None
    conversation_id = request.POST.get('conversation_id')
    if conversation_id:
        conversation = Conversation.objects.filter(id=conversation_id).first()
        if not conversation:
            return JsonResponse({'ok': False, 'error': '유효한 conversation_id가 필요합니다.'}, status=400)
        if conversation.survey_submission_id and conversation.survey_submission_id != submission.id:
            return JsonResponse({'ok': False, 'error': 'conversation과 submission 연결이 일치하지 않습니다.'}, status=400)

    replaces = None
    replaces_id = request.POST.get('replaces_id')
    if replaces_id:
        replaces = CaseDocument.objects.filter(id=replaces_id, submission=submission).first()
        if not replaces:
            return JsonResponse({'ok': False, 'error': '대체 대상 문서를 찾을 수 없습니다.'}, status=400)

    metadata = {}
    metadata_raw = request.POST.get('metadata') or ''
    if metadata_raw:
        try:
            parsed = json.loads(metadata_raw)
            if isinstance(parsed, dict):
                metadata = parsed
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'metadata는 JSON object 형식이어야 합니다.'}, status=400)

    is_signed_final_raw = str(request.POST.get('is_signed_final') or '').strip().lower()
    is_signed_final = is_signed_final_raw in {'1', 'true', 'yes', 'y'}

    try:
        document = create_case_document(
            submission=submission,
            uploaded_by=request.user,
            file=upload_file,
            document_type=document_type,
            document_scope=document_scope,
            visibility_level=visibility_level,
            owner_user=owner_user,
            conversation=conversation,
            status=status,
            replaces=replaces,
            metadata=metadata,
            is_signed_final=is_signed_final,
        )
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=403)

    return JsonResponse({'ok': True, 'document': _serialize_case_document(document, request)}, status=201)


@require_GET
@ensure_csrf_cookie
def api_case_document_detail(request, document_id):
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)

    document = (
        CaseDocument.objects.select_related('submission', 'owner_user', 'uploaded_by', 'conversation')
        .filter(id=document_id)
        .first()
    )
    if not document:
        return JsonResponse({'ok': False, 'error': '문서를 찾을 수 없습니다.'}, status=404)

    if not can_user_view_case_document(request.user, document):
        return JsonResponse({'ok': False, 'error': '권한이 없습니다.'}, status=403)

    return JsonResponse({'ok': True, 'document': _serialize_case_document(document, request)})


@require_GET
@ensure_csrf_cookie
def api_case_history_my(request):
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)

    role = getattr(request.user, 'role', None)
    role_cls = getattr(request.user, 'Role', None)
    if role != getattr(role_cls, 'CUSTOMER', 'CUSTOMER'):
        return JsonResponse({'ok': False, 'error': '고객 계정만 조회할 수 있습니다.'}, status=403)

    submission = resolve_customer_submission_for_history(
        request.user,
        submission_id=request.GET.get('submission_id'),
    )
    if not submission:
        return JsonResponse({'ok': False, 'error': '조회 가능한 케이스를 찾을 수 없습니다.'}, status=404)

    try:
        report = build_case_history_report(
            request.user,
            submission,
            customer_shared_only=True,
        )
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=403)

    return JsonResponse({'ok': True, 'report': _absolutize_report_file_urls(report, request)})


@require_GET
@ensure_csrf_cookie
def api_case_history_staff(request, submission_id):
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    if not getattr(request.user, 'is_internal_staff', lambda: False)():
        return JsonResponse({'ok': False, 'error': '내부 담당자만 조회할 수 있습니다.'}, status=403)

    submission = SurveySubmission.objects.filter(id=submission_id).first()
    if not submission:
        return JsonResponse({'ok': False, 'error': '케이스를 찾을 수 없습니다.'}, status=404)

    try:
        report = build_case_history_report(
            request.user,
            submission,
            customer_shared_only=False,
        )
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=403)

    return JsonResponse({'ok': True, 'report': _absolutize_report_file_urls(report, request)})
