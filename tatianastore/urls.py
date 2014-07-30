import os
import sys

from django.conf.urls import patterns, include, url
from django.conf import settings

# Uncomment the next two lines to enable the admin:
from django.contrib import admin
from django.conf.urls.static import static

from . import storefront
from . import storeadmin
from . import site
from . import signup


admin.autodiscover()


urlpatterns = patterns('',
    url(r'^$', 'tatianastore.site.index', name='index'),

    url(r'^blockchain_received/%s$' % settings.BLOCKCHAIN_WEBHOOK_SECRET, 'tatianastore.blockchain.blockchain_received', name='blockchain_received'),

    # Uncomment the next line to enable the admin:
    url(r'^admin/', include(admin.site.urls)),
    url(r'^store/', include(storefront)),
    url(r'^storeadmin/', include(storeadmin)),
    url(r'^site/', include(site)),
    url(r'^signup/', include(signup)),
    url(r'^accounts/', include('registration.backends.default.urls')),
)


if settings.DEBUG:
    # static files (images, css, javascript, etc.)
    urlpatterns += patterns('',
        (r'^media/(?P<path>.*)$', 'django.views.static.serve', {
        'document_root': settings.MEDIA_ROOT}))

# This is a hack to make static resources to load
# when doing runsslserver testing against FB
if "runsslserver" in sys.argv:
    static_path = os.path.join(os.path.dirname(__file__), "static")
    urlpatterns = urlpatterns + static(settings.STATIC_URL, document_root=static_path)