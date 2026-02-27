# Generated manually for message image attachment

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("messaging", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="message",
            name="body",
            field=models.TextField(blank=True, verbose_name="내용"),
        ),
        migrations.AddField(
            model_name="message",
            name="image",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="messaging/%Y/%m/",
                verbose_name="첨부 이미지",
            ),
        ),
    ]
