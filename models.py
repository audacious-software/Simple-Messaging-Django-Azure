# pylint: disable=line-too-long, no-member

from django.conf import settings
from django.core.checks import Warning, register # pylint: disable=redefined-builtin

@register()
def check_azure_settings_defined(app_configs, **kwargs): # pylint: disable=unused-argument
    errors = []

    if 'simple_messaging_switchboard' in settings.INSTALLED_APPS:
        from simple_messaging_switchboard.models import Channel # pylint: disable=import-outside-toplevel, import-error

        count = Channel.objects.filter(channel_type__package_name='simple_messaging_azure').count()

        if count == 0:
            error = Warning('simple_messaging_azure is installed alongside simple_messaging_switchboard, but no Channels are defined.', hint='Create Channel or consider removing simple_messaging_azure from settings.INSTALLED_APPS', obj=None, id='simple_messaging_azure.E001')
            errors.append(error)

    return errors
