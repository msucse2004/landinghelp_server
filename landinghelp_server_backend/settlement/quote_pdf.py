"""
견적서 PDF 생성. 고객 선호어·영어 2종 생성 후 이메일 첨부용으로 사용.
구조: 고객명/이메일, 견적 버전, 지역, 항목 목록, 합계, 약관/메모, 생성 시각.
한글 등 비ASCII 문자 정상 표시를 위해 TTF 폰트 등록 후 사용.
"""
import io
import logging
import os
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# PDF에 사용할 한글/CJK 지원 폰트 이름 (등록 후 사용)
PDF_FONT_CJK = 'QuotePDFCJK'
_cjk_font_registered = None


def _register_cjk_font():
    """
    한글/CJK 폰트 등록. 성공 시 True.
    탐색 순서: settings.QUOTATION_PDF_FONT_PATH → static/fonts/ → Windows → Linux(Noto CJK) → ReportLab CID 폰트.
    """
    global _cjk_font_registered
    if _cjk_font_registered is not None:
        return _cjk_font_registered
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    def _try_ttf(path):
        if not path or not os.path.isfile(path):
            return False
        try:
            pdfmetrics.registerFont(TTFont(PDF_FONT_CJK, path))
            logger.info("Quote PDF: registered TTF font %s", path)
            return True
        except Exception as e:
            logger.warning("Quote PDF: failed to register %s: %s", path, e)
            return False

    # 1) settings 직접 지정
    font_path = getattr(settings, 'QUOTATION_PDF_FONT_PATH', None)
    if font_path and _try_ttf(font_path):
        _cjk_font_registered = True
        return True

    # 2) 프로젝트 static/fonts/
    base_dir = getattr(settings, 'BASE_DIR', None)
    if base_dir:
        for name in ('NotoSansCJK-Regular.ttc', 'NotoSansKR-Regular.ttf', 'NotoSansKR-Regular.otf', 'NotoSansSC-Regular.ttf'):
            if _try_ttf(os.path.join(base_dir, 'static', 'fonts', name)):
                _cjk_font_registered = True
                return True

    # 3) Windows
    if os.name == 'nt':
        windir = os.environ.get('WINDIR', 'C:\\Windows')
        for name in ('malgun.ttf', 'gulim.ttc', 'batang.ttc', 'msyh.ttc', 'simsun.ttc'):
            if _try_ttf(os.path.join(windir, 'Fonts', name)):
                _cjk_font_registered = True
                return True

    # 4) Linux/Docker: Dockerfile에서 설치한 TTF 폰트 + 시스템 폰트
    _linux_font_dirs = [
        '/usr/share/fonts/truetype/custom',
        '/usr/share/fonts/truetype/noto',
        '/usr/share/fonts/opentype/noto',
        '/usr/share/fonts/truetype/nanum',
        '/usr/share/fonts/noto-cjk',
        '/usr/share/fonts',
        '/usr/local/share/fonts',
    ]
    _linux_font_names = [
        'NotoSansKR.ttf',
        'NotoSansKR-Regular.ttf',
        'NotoSansSC.ttf',
        'NotoSansSC-Regular.ttf',
        'NotoSans.ttf',
        'NotoSans-Regular.ttf',
        'NanumGothic.ttf',
    ]
    for d in _linux_font_dirs:
        if not os.path.isdir(d):
            continue
        for name in _linux_font_names:
            if _try_ttf(os.path.join(d, name)):
                _cjk_font_registered = True
                return True
        for root, dirs, files in os.walk(d):
            for name in _linux_font_names:
                if name in files:
                    if _try_ttf(os.path.join(root, name)):
                        _cjk_font_registered = True
                        return True
            break

    # 5) 최종 폴백: ReportLab 내장 CID 폰트 (TTF 없이도 한글/중국어 출력 가능)
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))
        _cjk_font_registered = True
        logger.info("Quote PDF: using CID font HYSMyeongJo-Medium (Korean)")
        return True
    except Exception:
        pass
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        _cjk_font_registered = True
        logger.info("Quote PDF: using CID font STSong-Light (Chinese)")
        return True
    except Exception:
        pass

    _cjk_font_registered = False
    logger.warning("Quote PDF: no CJK font found. Install fonts-noto-cjk or set QUOTATION_PDF_FONT_PATH.")
    return False


def _get_font_name():
    """등록된 폰트 이름 반환. CID 폰트가 등록된 경우 해당 이름, TTF면 PDF_FONT_CJK, 없으면 Helvetica."""
    if not _cjk_font_registered:
        return 'Helvetica'
    from reportlab.pdfbase import pdfmetrics
    if PDF_FONT_CJK in pdfmetrics.getRegisteredFontNames():
        return PDF_FONT_CJK
    if 'HYSMyeongJo-Medium' in pdfmetrics.getRegisteredFontNames():
        return 'HYSMyeongJo-Medium'
    if 'STSong-Light' in pdfmetrics.getRegisteredFontNames():
        return 'STSong-Light'
    return 'Helvetica'

PDF_LABELS = {
    'ko': {
        'quotation': '견적서',
        'quotation_no': '견적 번호',
        'date': '일자',
        'valid_until': '유효 기한',
        'bill_to': '청구처',
        'region': '지역',
        'description': '서비스',
        'amount': '금액 (USD)',
        'total': '합계',
        'terms': '약관',
        'generated_at': '생성 시각',
    },
    'en': {
        'quotation': 'Quotation',
        'quotation_no': 'Quotation No.',
        'date': 'Date',
        'valid_until': 'Valid Until',
        'bill_to': 'Bill To',
        'region': 'Region',
        'description': 'Description',
        'amount': 'Amount (USD)',
        'total': 'Total',
        'terms': 'Terms',
        'generated_at': 'Generated',
    },
    'es': {
        'quotation': 'Cotización',
        'quotation_no': 'No. de Cotización',
        'date': 'Fecha',
        'valid_until': 'Válido Hasta',
        'bill_to': 'Facturar A',
        'region': 'Región',
        'description': 'Descripción',
        'amount': 'Monto (USD)',
        'total': 'Total',
        'terms': 'Términos',
        'generated_at': 'Generado',
    },
    'zh-hans': {
        'quotation': '报价单',
        'quotation_no': '报价编号',
        'date': '日期',
        'valid_until': '有效期至',
        'bill_to': '收件方',
        'region': '地区',
        'description': '服务',
        'amount': '金额 (USD)',
        'total': '合计',
        'terms': '条款',
        'generated_at': '生成时间',
    },
    'zh-hant': {
        'quotation': '報價單',
        'quotation_no': '報價編號',
        'date': '日期',
        'valid_until': '有效期至',
        'bill_to': '收件方',
        'region': '地區',
        'description': '服務',
        'amount': '金額 (USD)',
        'total': '合計',
        'terms': '條款',
        'generated_at': '生成時間',
    },
    'vi': {
        'quotation': 'Báo Giá',
        'quotation_no': 'Số Báo Giá',
        'date': 'Ngày',
        'valid_until': 'Hiệu Lực Đến',
        'bill_to': 'Gửi Đến',
        'region': 'Khu Vực',
        'description': 'Mô Tả',
        'amount': 'Số Tiền (USD)',
        'total': 'Tổng Cộng',
        'terms': 'Điều Khoản',
        'generated_at': 'Tạo Lúc',
    },
}


def _get_label(language_code, key):
    """language_code에 맞는 PDF 라벨. 없으면 en fallback."""
    lang = (language_code or 'en').strip().lower()
    if lang not in PDF_LABELS:
        lang = lang[:2]
    if lang not in PDF_LABELS:
        lang = 'en'
    return PDF_LABELS[lang].get(key, PDF_LABELS['en'].get(key, key))


QUOTE_TERMS_BY_LANG = {
    'ko': '결제는 수락 시에 이루어집니다. 본 견적서는 위에 명시된 날짜까지 유효합니다. 서비스 및 가격은 주문 시 합의된 범위에 따릅니다.',
    'en': 'Payment due upon acceptance. This quotation is valid until the date stated above. Services and pricing are subject to the scope agreed at the time of order.',
    'es': 'El pago se realiza al aceptar. Esta cotización es válida hasta la fecha indicada anteriormente. Los servicios y precios están sujetos al alcance acordado al momento del pedido.',
    'zh-hans': '接受后即需付款。本报价单在上述日期前有效。服务和价格以下单时约定的范围为准。',
    'zh-hant': '接受後即需付款。本報價單在上述日期前有效。服務和價格以下單時約定的範圍為準。',
    'vi': 'Thanh toán khi chấp nhận. Báo giá này có hiệu lực đến ngày nêu trên. Dịch vụ và giá cả tuân theo phạm vi đã thống nhất khi đặt hàng.',
}
QUOTE_CONTACT_BY_LANG = {
    'ko': '문의 사항은 메시지 또는 이메일로 연락 주세요.',
    'en': 'For questions, please contact us via message or email.',
    'es': 'Para consultas, contáctenos por mensaje o correo electrónico.',
    'zh-hans': '如有疑问，请通过消息或电子邮件联系我们。',
    'zh-hant': '如有疑問，請通過訊息或電子郵件聯繫我們。',
    'vi': 'Nếu có câu hỏi, vui lòng liên hệ qua tin nhắn hoặc email.',
}


def _get_quotation_context(quote, language_code='en'):
    """견적서 메타 (회사명, 견적번호 Q-YYYY-MM-DD-N, 유효기한 10일, 약관·문의 문구 언어별)."""
    from datetime import timedelta
    from .models import SettlementQuote
    now = timezone.now()
    company = getattr(settings, 'QUOTATION_COMPANY_NAME', 'LifeAI US')
    valid_days = 10  # 견적일자 기준 10일
    valid_until = (now + timedelta(days=valid_days)).strftime('%Y-%m-%d')
    lang = (language_code or 'en').strip().lower()[:2]
    terms = QUOTE_TERMS_BY_LANG.get(lang) or QUOTE_TERMS_BY_LANG['en']
    contact_footer = QUOTE_CONTACT_BY_LANG.get(lang) or QUOTE_CONTACT_BY_LANG['en']
    qdate = quote.created_at.date() if getattr(quote, 'created_at', None) else now.date()
    daily_seq = SettlementQuote.objects.filter(
        created_at__date=qdate, id__lte=quote.id
    ).count()
    quotation_number = f'Q-{qdate:%Y-%m-%d}-{daily_seq}'
    quotation_date = qdate.strftime('%Y-%m-%d')
    return {
        'company_name': company,
        'quotation_number': quotation_number,
        'quotation_date': quotation_date,
        'valid_until': valid_until,
        'terms': terms,
        'contact_footer': contact_footer,
        'generated_at': now.strftime('%Y-%m-%d %H:%M UTC'),
    }


def build_quote_pdf_bytes(quote, language_code='en'):
    """
    단일 견적서 PDF 바이트 생성.
    quote: SettlementQuote (submission, items, total, region 등)
    language_code: 'ko', 'en' 등. PDF 내 라벨/헤더에 사용.
    Returns: bytes (PDF 파일 내용). 실패 시 None.
    """
    if not quote:
        return None
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as e:
        logger.warning("reportlab not available for quote PDF: %s", e)
        return None

    _register_cjk_font()
    font_name = _get_font_name()

    buf = io.BytesIO()
    labels = {k: _get_label(language_code, k) for k in PDF_LABELS['en']}
    ctx = _get_quotation_context(quote, language_code=language_code)
    submission = getattr(quote, 'submission', None)
    customer_name = (submission.email or '-') if submission else '-'
    if submission and getattr(submission, 'user', None) and submission.user:
        fn = (submission.user.get_full_name() or '').strip()
        if fn:
            customer_name = fn + ' <' + (submission.email or '') + '>'
        else:
            customer_name = submission.email or '-'
    region = (getattr(quote, 'region', None) or '').strip() or '-'

    try:
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'QuoteTitle',
            parent=styles['Heading1'],
            fontName=font_name,
            fontSize=16,
            spaceAfter=12,
            alignment=1,
        )
        normal = ParagraphStyle(
            'QuoteNormal',
            parent=styles['Normal'],
            fontName=font_name,
        )
        small = ParagraphStyle(
            'QuoteSmall',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=9,
            spaceAfter=6,
        )
        heading2 = ParagraphStyle(
            'QuoteH2',
            parent=styles['Heading2'],
            fontName=font_name,
        )
        heading3 = ParagraphStyle(
            'QuoteH3',
            parent=styles['Heading3'],
            fontName=font_name,
        )

        story = []
        story.append(Paragraph(ctx['company_name'], title_style))
        story.append(Paragraph(labels['quotation'], heading2))
        story.append(Spacer(1, 6))

        story.append(Paragraph(f"{labels['quotation_no']}: {ctx['quotation_number']}", normal))
        story.append(Paragraph(f"{labels['date']}: {ctx['quotation_date']}", normal))
        story.append(Paragraph(f"{labels['valid_until']}: {ctx['valid_until']}", normal))
        story.append(Spacer(1, 10))

        story.append(Paragraph(labels['bill_to'], heading3))
        story.append(Paragraph(customer_name.replace('&', '&amp;'), normal))
        story.append(Paragraph(f"{labels['region']}: {region}", normal))
        story.append(Spacer(1, 12))

        items = getattr(quote, 'items', None) or []
        total_val = float(quote.total or 0)
        lang = (language_code or 'en').strip().lower()[:2]
        data = [[labels['description'], labels['amount']]]
        for it in items:
            if not isinstance(it, dict):
                continue
            raw_label = it.get('label') or it.get('code') or '-'
            if lang != 'ko':
                try:
                    from translations.utils import get_display_text
                    display_label = (get_display_text(raw_label, lang) or '').strip()
                    if not display_label or display_label == raw_label:
                        code = it.get('code') or ''
                        display_label = (get_display_text(code, lang) or '').strip() if code else raw_label
                    if not display_label:
                        display_label = raw_label
                except Exception:
                    display_label = raw_label
            else:
                display_label = raw_label
            label = (display_label or '-').replace('&', '&amp;')
            price = it.get('price')
            if price is not None:
                price_str = f"${float(price):,.2f}"
            else:
                price_str = "-"
            data.append([label, price_str])
        data.append([labels['total'], f"${total_val:,.2f}"])

        t = Table(data, colWidths=[doc.width * 0.75, doc.width * 0.25])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#1e293b')),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor('#1e293b')),
            ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        story.append(t)
        story.append(Spacer(1, 12))

        if ctx.get('terms'):
            story.append(Paragraph(labels['terms'], heading3))
            story.append(Paragraph(ctx['terms'].replace('&', '&amp;'), small))
        if ctx.get('contact_footer'):
            story.append(Paragraph(ctx['contact_footer'].replace('&', '&amp;'), small))
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"{labels['generated_at']}: {ctx['generated_at']}", small))

        doc.build(story)
        return buf.getvalue()
    except Exception as e:
        logger.warning("build_quote_pdf_bytes failed: quote_id=%s lang=%s error=%s", getattr(quote, 'id'), language_code, e, exc_info=True)
        return None
