import csv
import io
from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.core.management import call_command
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path
from django.utils.encoding import force_str

from .models import StaticTranslation, LANG_COLUMNS, LANG_CSV_HEADERS


def _short(val, max_len=50):
    if not val:
        return ''
    s = force_str(val).strip()
    return s[:max_len] + ('…' if len(s) > max_len else '')


@admin.register(StaticTranslation)
class StaticTranslationAdmin(admin.ModelAdmin):
    list_display = ('key', 'ko_short', 'en_short', 'es_short', 'zh_hans_short', 'zh_hant_short', 'vi_short')
    list_filter = ()
    search_fields = ('key', 'ko', 'en', 'es', 'zh_hans', 'zh_hant', 'vi')
    list_editable = ()

    def ko_short(self, obj):
        return _short(obj.ko)
    ko_short.short_description = 'ko'

    def en_short(self, obj):
        return _short(obj.en)
    en_short.short_description = 'en'

    def es_short(self, obj):
        return _short(obj.es)
    es_short.short_description = 'es'

    def zh_hans_short(self, obj):
        return _short(obj.zh_hans)
    zh_hans_short.short_description = 'zh-hans'

    def zh_hant_short(self, obj):
        return _short(obj.zh_hant)
    zh_hant_short.short_description = 'zh-hant'

    def vi_short(self, obj):
        return _short(obj.vi)
    vi_short.short_description = 'vi'

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('export-csv/', self.admin_site.admin_view(self.export_csv_view), name='translations_statictranslation_export_csv'),
            path('import-csv/', self.admin_site.admin_view(self.import_csv_view), name='translations_statictranslation_import_csv'),
            path('sync-keys-and-csv/', self.admin_site.admin_view(self.sync_keys_and_csv_view), name='translations_statictranslation_sync_keys_and_csv'),
        ]
        return custom + urls

    def export_csv_view(self, request):
        """CSV 내보내기. 헤더: key, ko, en, es, zh-hans, zh-hant, vi. 키 오름차순 정렬."""
        qs = StaticTranslation.objects.all().order_by('key')  # 키 오름차순
        buf = io.StringIO()
        buf.write('\ufeff')
        writer = csv.writer(buf, lineterminator='\n')
        writer.writerow(LANG_CSV_HEADERS)
        for row in qs:
            writer.writerow([
                row.key or '',
                row.ko or '',
                row.en or '',
                row.es or '',
                row.zh_hans or '',
                row.zh_hant or '',
                row.vi or '',
            ])
        body = buf.getvalue()
        resp = HttpResponse(body, content_type='text/csv; charset=utf-8-sig')
        resp['Content-Disposition'] = 'attachment; filename="static_translations.csv"'
        resp['Content-Length'] = len(body.encode('utf-8-sig'))
        return resp

    def import_csv_view(self, request):
        """CSV 가져오기. 형식: key, ko, en, es, zh-hans, zh-hant, vi (헤더 첫 줄 제거)"""
        if request.method != 'POST':
            return render(request, 'admin/translations/import_csv.html', {
                'title': '고정 번역 CSV 가져오기',
                'opts': self.model._meta,
                'headers': LANG_CSV_HEADERS,
            })
        f = request.FILES.get('csv_file')
        if not f:
            return render(request, 'admin/translations/import_csv.html', {
                'title': '고정 번역 CSV 가져오기',
                'opts': self.model._meta,
                'headers': LANG_CSV_HEADERS,
                'error': 'CSV 파일을 선택하세요.',
            })
        try:
            content = f.read().decode('utf-8-sig').strip()
        except Exception as e:
            return render(request, 'admin/translations/import_csv.html', {
                'title': '고정 번역 CSV 가져오기',
                'opts': self.model._meta,
                'headers': LANG_CSV_HEADERS,
                'error': f'파일 인코딩 오류: {e}',
            })
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        if not rows:
            return render(request, 'admin/translations/import_csv.html', {
                'title': '고정 번역 CSV 가져오기',
                'opts': self.model._meta,
                'headers': LANG_CSV_HEADERS,
                'error': 'CSV에 행이 없습니다.',
            })
        # 헤더: key, ko, en, es, zh-hans, zh-hant, vi
        header = [str(c).strip().lower() for c in rows[0]]
        if header[0] == 'key':
            rows = rows[1:]
        # 컬럼 인덱스: 0=key, 1=ko, 2=en, 3=es, 4=zh-hans, 5=zh-hant, 6=vi
        idx_key, idx_ko, idx_en, idx_es, idx_zh_hans, idx_zh_hant, idx_vi = 0, 1, 2, 3, 4, 5, 6
        created = updated = 0
        for row in rows:
            if len(row) < 1:
                continue
            key = (row[idx_key] or '').strip()
            if not key:
                continue
            def cell(i):
                return (row[i] or '').strip() if i < len(row) else ''
            obj, created_ = StaticTranslation.objects.update_or_create(
                key=key,
                defaults={
                    'ko': cell(idx_ko),
                    'en': cell(idx_en),
                    'es': cell(idx_es),
                    'zh_hans': cell(idx_zh_hans),
                    'zh_hant': cell(idx_zh_hant),
                    'vi': cell(idx_vi),
                },
            )
            if created_:
                created += 1
            else:
                updated += 1
        return render(request, 'admin/translations/import_csv_done.html', {
            'title': '고정 번역 CSV 가져오기',
            'opts': self.model._meta,
            'created': created,
            'updated': updated,
        })

    def sync_keys_and_csv_view(self, request):
        """키 동기화(seed_translation_keys) 후 프로젝트 루트 CSV로 번역 반영."""
        if request.method != 'POST':
            csv_path = Path(settings.BASE_DIR) / 'static_translations_all.csv'
            return render(request, 'admin/translations/sync_keys_and_csv.html', {
                'title': '키 동기화 및 CSV 반영',
                'opts': self.model._meta,
                'csv_path': csv_path,
                'csv_exists': csv_path.exists(),
            })
        # 1) 키 동기화
        from io import StringIO
        out = StringIO()
        try:
            call_command('seed_translation_keys', stdout=out)
            keys_out = out.getvalue().strip()
        except Exception as e:
            keys_out = str(e)
            keys_created = 0
        else:
            keys_created = None  # 메시지에서 파싱하지 않고 "실행됨"으로 표시

        # 2) CSV 반영
        csv_path = Path(settings.BASE_DIR) / 'static_translations_all.csv'
        csv_created = csv_updated = 0
        csv_error = None
        if csv_path.exists():
            try:
                with open(csv_path, 'r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                if rows:
                    header = [str(c).strip().lower() for c in rows[0]]
                    if header and header[0] == 'key':
                        rows = rows[1:]
                    idx_key, idx_ko, idx_en, idx_es, idx_zh_hans, idx_zh_hant, idx_vi = 0, 1, 2, 3, 4, 5, 6
                    for row in rows:
                        if len(row) < 1:
                            continue
                        key = (row[idx_key] or '').strip()
                        if not key:
                            continue

                        def cell(i):
                            return (row[i] or '').strip() if i < len(row) else ''

                        _, created_ = StaticTranslation.objects.update_or_create(
                            key=key,
                            defaults={
                                'ko': cell(idx_ko),
                                'en': cell(idx_en),
                                'es': cell(idx_es),
                                'zh_hans': cell(idx_zh_hans),
                                'zh_hant': cell(idx_zh_hant),
                                'vi': cell(idx_vi),
                            },
                        )
                        if created_:
                            csv_created += 1
                        else:
                            csv_updated += 1
            except Exception as e:
                csv_error = str(e)
        else:
            csv_error = f'CSV 파일 없음: {csv_path}'

        return render(request, 'admin/translations/sync_keys_and_csv_done.html', {
            'title': '키 동기화 및 CSV 반영',
            'opts': self.model._meta,
            'keys_output': keys_out,
            'csv_created': csv_created,
            'csv_updated': csv_updated,
            'csv_error': csv_error,
        })
