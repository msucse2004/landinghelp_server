# Generated: 메시지 다국어 - 감지 언어, 영어 번역 저장

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("messaging", "0002_message_image_message_body_blank"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="detected_lang",
            field=models.CharField(
                blank=True,
                max_length=10,
                verbose_name="감지된 언어",
                help_text="langdetect 결과 (ko, en 등). 영어가 아니면 body_en에 번역 저장.",
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="body_en",
            field=models.TextField(
                blank=True,
                verbose_name="영어 번역",
                help_text="원문이 영어가 아닐 때 DeepL로 번역한 영어 본문.",
            ),
        ),
    ]
