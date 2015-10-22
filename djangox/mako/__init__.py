import traceback
import os
import sys
import types
import warnings

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse, HttpResponseServerError
from django.template.backends.base import BaseEngine
from django.template.context import RequestContext, Context, make_context
from django.template.engine import Engine, _dirs_undefined
from django.utils.deprecation import RemovedInDjango20Warning
from django.utils.importlib import import_module
from django.utils.translation import ugettext
from mako.lookup import TemplateLookup
from mako import exceptions
from django.core.urlresolvers import reverse, get_resolver, get_urlconf
from django.templatetags import static
from mako.template import Template


def url(view_name, *args, **kwargs):
    try:
        return reverse(view_name, args=args, kwargs=kwargs)
    except:
        resolver = get_resolver(get_urlconf())
        for key in resolver.reverse_dict.keys():
            if isinstance(key, types.FunctionType):
                name = key.__module__ + '.' + key.__name__
            else:
                name = key
            
            if name.endswith(view_name):
                return reverse(name, args=args, kwargs=kwargs)
        
        raise
        

default_context = {
    'url' : url,
    'static': static.static,
    '_': ugettext,
}

default_charset = getattr(settings, 'DEFAULT_CHARSET', 'utf8')

app_template_dirs = []
fs_encoding = sys.getfilesystemencoding() or sys.getdefaultencoding()

for app in settings.INSTALLED_APPS:
    try:
        mod = import_module(app)
    except ImportError as e:
        raise ImproperlyConfigured('ImportError %s: %s' % (app, e.args[0]))
    template_dir = os.path.join(os.path.dirname(mod.__file__), 'templates')
    if os.path.isdir(template_dir):
        app_template_dirs.append(template_dir)


template_lookup = TemplateLookup(directories=app_template_dirs, 
                                 input_encoding=default_charset, 
                                 output_encoding=default_charset, 
                                 )

def render_to_response(filename, dictionary, context_instance=None):
    '''
    :param filename:
    :param dictionary:
    :param context_instance:
    :return: rendered django HttpResponse
    '''

    dictionary.update(default_context)

    if context_instance:
        for context_dict in context_instance.dicts:
            dictionary.update(context_dict)

    if hasattr(settings, 'MAKO_DEFAULT_CONTEXT'):
        dictionary.update(settings.MAKO_DEFAULT_CONTEXT)

    try:
        template = template_lookup.get_template(filename)
        return HttpResponse(template.render(**dictionary))
    except exceptions.TopLevelLookupException:
        raise
    except:
        traceback.print_exc()
        return HttpResponseServerError(exceptions.html_error_template().render())


class MakoTemplateEngine(BaseEngine):

    app_dirname = 'templates'

    def __init__(self, params):
        params = params.copy()
        options = params.pop('OPTIONS').copy()
        options.setdefault('debug', settings.DEBUG)
        options.setdefault('file_charset', settings.FILE_CHARSET)
        super().__init__(params)
        self.engine = Engine(self.dirs, self.app_dirs, **options)

    def from_string(self, template_code):
        return MakoTemplateWrapper(Template(text=template_code))

    def get_template(self, template_name, dirs=_dirs_undefined):
        return MakoTemplateWrapper(template_lookup.get_template(template_name))


class MakoTemplateWrapper(object):

    def __init__(self, template):
        self.template = template
        self.engine = Engine.get_default()

    @property
    def origin(self):
        # TODO: define the Origin API. For now simply forwarding to the
        #       underlying Template preserves backwards-compatibility.
        return self.template

    def render(self, context=None, request=None):
        # A deprecation path is required here to cover the following usage:
        # >>> from django.template import Context
        # >>> from django.template.loader import get_template
        # >>> template = get_template('hello.html')
        # >>> template.render(Context({'name': 'world'}))
        # In Django 1.7 get_template() returned a django.template.Template.
        # In Django 1.8 it returns a django.template.backends.django.Template.
        # In Django 2.0 the isinstance checks should be removed. If passing a
        # Context or a RequestContext works by accident, it won't be an issue
        # per se, but it won't be officially supported either.
        if isinstance(context, RequestContext):
            if request is not None and request is not context.request:
                raise ValueError(
                    "render() was called with a RequestContext and a request "
                    "argument which refer to different requests. Make sure "
                    "that the context argument is a dict or at least that "
                    "the two arguments refer to the same request.")
            warnings.warn(
                "render() must be called with a dict, not a RequestContext.",
                RemovedInDjango20Warning, stacklevel=2)

        elif isinstance(context, Context):
            warnings.warn(
                "render() must be called with a dict, not a Context.",
                RemovedInDjango20Warning, stacklevel=2)

        else:
            context = make_context(context, request)

        if hasattr(settings, 'MAKO_DEFAULT_CONTEXT'):
            context.dicts.append(settings.MAKO_DEFAULT_CONTEXT)

        context.dicts.append(default_context)
        try:
            with context.bind_template(self):
                return self.template.render(**context.flatten())
        except exceptions.TopLevelLookupException:
            raise
        except:
            traceback.print_exc()
            return exceptions.html_error_template().render()

