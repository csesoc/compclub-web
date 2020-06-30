# Generated by Django 3.0.6 on 2020-06-30 02:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0017_auto_20200615_1646'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='event',
            options={'permissions': [('view_hidden_event', 'Can view hidden events'), ('view_unreleased_event', 'Can view events that are unreleased')]},
        ),
        migrations.AddField(
            model_name='event',
            name='hidden_event',
            field=models.BooleanField(default=True, help_text='Users cannot view the event (including on the home page and events feed)'),
        ),
        migrations.AddField(
            model_name='event',
            name='released',
            field=models.BooleanField(default=True, help_text='Leave this checked if you want to automatically release the event on the start date (at midnight).'),
        ),
        migrations.AlterField(
            model_name='event',
            name='start_date',
            field=models.DateField(help_text='Users without the view_unreleased_event permission cannot see the event until start date and the event is released.'),
        ),
    ]