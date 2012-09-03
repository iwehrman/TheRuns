from django.conf.urls.defaults import patterns, include, url

urlpatterns = patterns('run.views',
    # Examples:
    # url(r'^$', 'fit.views.home', name='home'),
    # url(r'^fit/', include('fit.foo.urls')),

    # Uncomment the admin/doc line below to enable admin documentation:
    # url(r'^admin/doc/', include('django.contrib.admindocs.urls')),

    # Uncomment the next line to enable the admin:
    url(r'^$', 'index'),
    url(r'^_about/$', 'do_about'),
    url(r'^_splash/$', 'do_splash'),
    url(r'^_signup/$', 'do_signup'),
    url(r'^_login/$', 'do_login'),
    url(r'^_logout/$', 'do_logout'),
    url(r'^_bounce/(?P<rest>.+)$', 'do_bounce'),
    url(r'^_reset_start/$', 'password_reset_start'),
    url(r'^_reset_finish/$', 'password_reset_finish'),
    url(r'^(?P<username>\w+)/$', 'index_user'),
    url(r'^(?P<username>\w+)/all$', 'all_user'),
    url(r'^(?P<username>\w+)/yield$', 'yield_user'),
    url(r'^(?P<username>\w+)/profile/$', 'userprofile'),
    url(r'^(?P<username>\w+)/profile/update/$', 'userprofile_update'),
    url(r'^(?P<username>\w+)/profile/delete/$', 'userprofile_delete'),
    url(r'^(?P<username>\w+)/import/$', 'do_import'),
    url(r'^(?P<username>\w+)/export/$', 'do_export'),
    url(r'^(?P<username>\w+)/shoe/all/$', 'shoe_all'),
    url(r'^(?P<username>\w+)/shoe/new/$', 'shoe_new'),
    url(r'^(?P<username>\w+)/shoe/remove/(?P<shoe_id>\d+)/$', 'shoe_delete'),
    url(r'^(?P<username>\w+)/shoe/retire/(?P<shoe_id>\d+)/$', 'shoe_retire'),
    url(r'^(?P<username>\w+)/shoe/activate/(?P<shoe_id>\d+)/$', 'shoe_activate'),
    url(r'^(?P<username>\w+)/run/all/$', 'run_all'),
    url(r'^(?P<username>\w+)/run/new/$', 'run_new'),
    url(r'^(?P<username>\w+)/run/update/$', 'run_update'),
    url(r'^(?P<username>\w+)/run/remove/(?P<run_id>\d+)/$', 'run_delete'),
)