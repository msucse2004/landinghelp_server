# Generated manually for wide format: key + ko, en, es, zh_hans, zh_hant, vi

from django.db import migrations, models


def migrate_to_wide(apps, schema_editor):
    """기존 (key, language_code, value) 행들을 key당 한 행(wide)으로 합침."""
    StaticTranslation = apps.get_model('translations', 'StaticTranslation')
    # 이 마이그레이션 적용 시점에는 아직 language_code, value 필드가 있음
    if not hasattr(StaticTranslation, 'language_code'):
        return
    lang_to_field = {'ko': 'ko', 'en': 'en', 'es': 'es', 'zh-hans': 'zh_hans', 'zh-hant': 'zh_hant', 'vi': 'vi'}
    seen_keys = set()
    for row in StaticTranslation.objects.all().order_by('key', 'id'):
        k = (row.key or '').strip()
        if not k:
            continue
        if k in seen_keys:
            continue
        seen_keys.add(k)
        # 이 key에 대한 모든 행 수집
        rows_for_key = list(StaticTranslation.objects.filter(key=k).order_by('id'))
        first = rows_for_key[0]
        for r in rows_for_key:
            lc = (r.language_code or '').strip()
            field = lang_to_field.get(lc)
            if field and hasattr(first, field):
                setattr(first, field, (r.value or '')[:1000])
        first.save()
        # 첫 행 제외 나머지 삭제
        for r in rows_for_key[1:]:
            r.delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('translations', '0001_initial'),
    ]

    operations = [
        # 1) unique_together 제거 (나중에 key unique로 대체)
        migrations.AlterUniqueTogether(
            name='statictranslation',
            unique_together=set(),
        ),
        # 2) 새 컬럼 추가
        migrations.AddField(
            model_name='statictranslation',
            name='ko',
            field=models.CharField(blank=True, default='', max_length=1000, verbose_name='한국어'),
        ),
        migrations.AddField(
            model_name='statictranslation',
            name='en',
            field=models.CharField(blank=True, default='', max_length=1000, verbose_name='English'),
        ),
        migrations.AddField(
            model_name='statictranslation',
            name='es',
            field=models.CharField(blank=True, default='', max_length=1000, verbose_name='Español'),
        ),
        migrations.AddField(
            model_name='statictranslation',
            name='zh_hans',
            field=models.CharField(blank=True, default='', max_length=1000, verbose_name='中文(简体)'),
        ),
        migrations.AddField(
            model_name='statictranslation',
            name='zh_hant',
            field=models.CharField(blank=True, default='', max_length=1000, verbose_name='中文(繁體)'),
        ),
        migrations.AddField(
            model_name='statictranslation',
            name='vi',
            field=models.CharField(blank=True, default='', max_length=1000, verbose_name='Tiếng Việt'),
        ),
        # 3) 데이터 이전: key당 한 행으로 합치기
        migrations.RunPython(migrate_to_wide, noop_reverse),
        # 4) 구 컬럼 제거
        migrations.RemoveField(
            model_name='statictranslation',
            name='language_code',
        ),
        migrations.RemoveField(
            model_name='statictranslation',
            name='value',
        ),
        # 5) key unique
        migrations.AlterField(
            model_name='statictranslation',
            name='key',
            field=models.CharField(
                db_index=True,
                help_text='템플릿/코드에서 사용하는 문구(예: 로그아웃, 이메일)',
                max_length=500,
                unique=True,
                verbose_name='원문(키)',
            ),
        ),
        migrations.AlterModelOptions(
            name='statictranslation',
            options={'ordering': ['key'], 'verbose_name': '고정 번역', 'verbose_name_plural': '고정 번역'},
        ),
    ]
