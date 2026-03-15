# 서비스별 State별 가격 테이블 추가

from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0018_categorize_services'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceStatePrice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('state_code', models.CharField(db_index=True, help_text='예: CA, NC, NY (2글자 권장)', max_length=10, verbose_name='State 코드')),
                ('customer_price', models.DecimalField(decimal_places=0, default=Decimal('0'), max_digits=12, verbose_name='Customer 가격 (USD)')),
                ('agent_price', models.DecimalField(decimal_places=0, default=Decimal('0'), max_digits=12, verbose_name='Agent 가격 (USD)')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('service', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='state_prices', to='settlement.settlementservice', verbose_name='서비스')),
            ],
            options={
                'verbose_name': '서비스 State별 가격',
                'verbose_name_plural': '서비스 State별 가격',
                'ordering': ['service', 'state_code'],
                'unique_together': {('service', 'state_code')},
            },
        ),
    ]
