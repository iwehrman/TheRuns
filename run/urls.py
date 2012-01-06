from django.conf.urls.defaults import patterns, include, url

urlpatterns = patterns('run.views',
    # Examples:
    # url(r'^$', 'fit.views.home', name='home'),
    # url(r'^fit/', include('fit.foo.urls')),

    # Uncomment the admin/doc line below to enable admin documentation:
    # url(r'^admin/doc/', include('django.contrib.admindocs.urls')),

    # Uncomment the next line to enable the admin:
    url(r'^$', 'index'),
    url(r'^u/(?P<username>.+)/$', 'index_user'),
    url(r'^login/$', 'do_login'),
    url(r'^logout/$', 'do_logout'),
    url(r'^reset_start/$', 'password_reset_start'),
    url(r'^reset_finish/$', 'password_reset_finish'),
    url(r'^profile/$', 'userprofile'),
    url(r'^export/$', 'export'),
    url(r'^profile/update/$', 'userprofile_update'),
    url(r'^shoe/all/$', 'shoe_all'),
    url(r'^shoe/new/$', 'shoe_new'),
    url(r'^shoe/update/$', 'shoe_update'),
    url(r'^shoe/remove/(?P<shoe_id>\d+)/$', 'shoe_delete'),
    url(r'^shoe/retire/(?P<shoe_id>\d+)/$', 'shoe_retire'),
    url(r'^run/(?P<run_id>\d+)/$', 'run_detail'),
    url(r'^run/all/$', 'run_all'),
    url(r'^run/new/$', 'run_new'),
    url(r'^run/update/$', 'run_update'),
    url(r'^run/remove/(?P<run_id>\d+)/$', 'run_delete'),
)