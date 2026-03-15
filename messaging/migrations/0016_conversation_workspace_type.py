from django.db import migrations, models


def forward_fill_workspace_types(apps, schema_editor):
    Conversation = apps.get_model('messaging', 'Conversation')
    Conversation.objects.filter(type='APPOINTMENT').update(workspace_type='APPOINTMENT')
    Conversation.objects.exclude(type='APPOINTMENT').update(workspace_type='OTHER')


def backward_fill_workspace_types(apps, schema_editor):
    Conversation = apps.get_model('messaging', 'Conversation')
    Conversation.objects.update(workspace_type='OTHER')


class Migration(migrations.Migration):

    dependencies = [
        ('messaging', '0015_rename_messaging_c_label_q_8e0e0d_idx_messaging_c_label_q_1dc760_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='workspace_type',
            field=models.CharField(
                choices=[
                    ('HQ_BACKOFFICE', '본사업무방'),
                    ('LOCAL_EXECUTION', '현지진행방'),
                    ('APPOINTMENT', '약속 대화'),
                    ('OTHER', '기타'),
                ],
                db_index=True,
                default='OTHER',
                max_length=30,
                verbose_name='워크스페이스 타입',
            ),
        ),
        migrations.RunPython(forward_fill_workspace_types, backward_fill_workspace_types),
        migrations.AddConstraint(
            model_name='conversation',
            constraint=models.UniqueConstraint(
                condition=models.Q(('survey_submission__isnull', False), ('workspace_type', 'HQ_BACKOFFICE')),
                fields=('survey_submission', 'workspace_type'),
                name='unique_hq_workspace_per_submission',
            ),
        ),
        migrations.AddConstraint(
            model_name='conversation',
            constraint=models.UniqueConstraint(
                condition=models.Q(('survey_submission__isnull', False), ('workspace_type', 'LOCAL_EXECUTION')),
                fields=('survey_submission', 'workspace_type'),
                name='unique_local_workspace_per_submission',
            ),
        ),
    ]
