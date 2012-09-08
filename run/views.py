import datetime, calendar, logging, random, json
from datetime import date, time, timedelta
from decimal import Decimal
from urllib import urlencode

from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.mail import send_mail
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.urlresolvers import reverse
from django.db.models import Min
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseForbidden, Http404
from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext
from django.views.decorators.http import condition
from django.views.decorators.cache import cache_control

from django_recaptcha_field import create_form_subclass_with_recaptcha
from recaptcha import RecaptchaClient

from run.models import UserProfile, Shoe, Run, hms_to_time, Aggregate
from run.forms import UserForm, NewUserForm, UserProfileForm, ImportForm

BASE_URI = "http://get.theruns.in"
MAIL_FROM_ADDR = "admin@theruns.in"

log = logging.getLogger(__name__)

recaptcha_client = RecaptchaClient('6LeP-tUSAAAAABJA06RqAXcoPsIpaGfvhvlyRPUA', 
    '6LeP-tUSAAAAAPnvQazfnpwwIY7NnUxINzWTIv5K')

WEEK_USER_AG_PREFIX = 'WEEK_AG'
MONTH_USER_AG_PREFIX = 'MONTH_AG'
WEEK_ALL_AG_PREFIX = 'WEEK_ALL_AG'
MONTH_ALL_AG_PREFIX = 'MONTH_ALL_AG'
LM_PREFIX = 'LM'
FIRST_PREFIX = 'FIRST'

ONE_DAY = timedelta(days=1)
ONE_WEEK = timedelta(days=7)

def ag_cache_key(prefix, user, date): 
    if user: 
        return "%s_%d_%d_%d_%d" % (prefix, user.id, date.year, date.month, date.day)
    else: 
        return "%s_%d_%d_%d" % (prefix, date.year, date.month, date.day)

def lm_cache_key(userid):
    return "%s_%d" % (LM_PREFIX,userid)
    
def first_date_cache_key(userid):
    return "%s_%d" % (FIRST_PREFIX, userid)

def aggregate_runs(user, first_day, last_day):
    MAX_CONST = 1000000 # ought to be enough for anyone 
    
    duration = 0
    distance = 0
    total_distance_in_meters = 0
    hr_distance_in_meters = 0
    hr_duration_in_seconds = 0
    heartbeats = 0
    calories = 0
    minimum = MAX_CONST
    maximum = 0

    if user: 
        runs = (Run.objects.filter(user=user.id)
            .filter(date__gte=first_day).filter(date__lte=last_day))
    else: # user == None means aggregate all users
        runs = (Run.objects.all()
            .filter(date__gte=first_day).filter(date__lte=last_day))

    for run in runs: 
        duration += run.duration_in_seconds()
        distance += run.distance
        total_distance_in_meters += run.distance_in_meters()
        calories += run.calories
        if run.average_heart_rate:
            hr_distance_in_meters += run.distance_in_meters()
            hr_duration_in_seconds += run.duration_in_seconds()
            heartbeats += run.heartbeats()
        if run.distance < minimum: 
            minimum = run.distance
        if run.distance > maximum: 
            maximum = run.distance

    if minimum == MAX_CONST: 
        minimum = 0

    if duration > 0: 
        speed = total_distance_in_meters / duration
    else:
        speed = None
    
    if len(runs) > 0: 
        average = distance / len(runs)
    else: 
        average = 0
        
    if hr_duration_in_seconds > 0: 
        beats_per_second = (heartbeats / hr_duration_in_seconds)
        heart_rate = beats_per_second * 60
    else: 
        heart_rate = None
        beats_per_second = None
        
    efficiency = Run.compute_efficiency(hr_distance_in_meters, heartbeats)
    if not efficiency > 0: 
        efficiency = None
        
    ag = Aggregate()
    ag.distance = distance
    ag.minimum = minimum
    ag.maximum = maximum 
    ag.average = average
    ag.pace = Run.compute_pace(duration, distance)
    ag.efficiency = efficiency
    ag.speed = speed
    ag.calories = calories
    ag.first_date = first_day
    ag.last_date = last_day
    ag.heart_rate = heart_rate
    ag.beats_per_second = beats_per_second

    if user: # if aggregating all users, don't store in DB
        ag.user = user
        ag.save()

    return ag
    
def get_aggregate_from_db(user, first_date, last_date):
    if user: 
        ags = Aggregate.objects.filter(user=user.id, 
            first_date=first_date, last_date=last_date)
    else: # aggregates for everyone not stored in DB
        ags = []

    if len(ags) == 1:
        # log.debug("Aggregate DB HIT: %s" % ags[0])
        return ags[0]
    elif len(ags) == 0: 
        ag = aggregate_runs(user, first_date, last_date)
        log.info("Aggregate DB MISS: %s" % ag)
        return ag
    else: 
        # FYI: this has happened at least once, but I'm not sure why. 
        # It might be wise to just invalidate the cache and regenerate the 
        # aggregates from the DB
        raise Exception("Multiple aggregates for %s at %s - %s" % 
            (user.username, first_date, last_date))
            
def invalidate_cache(user, date):
    # invalidate aggregates
    ags = Aggregate.objects.filter(user=user.id,first_date__lte=date,
        last_date__gte=date)
    
    week_keys = [ag_cache_key(WEEK_USER_AG_PREFIX,user,ag.first_date) for ag in ags]
    log.info("Evicting %s from week_cache", cache.get_many(week_keys))
    cache.delete_many(week_keys)
    month_keys = [ag_cache_key(MONTH_USER_AG_PREFIX,user,ag.first_date) for ag in ags]
    log.info("Evicting %s from month_cache", cache.get_many(month_keys))
    cache.delete_many(month_keys)

    ags.delete()
    
    # invalidate first-date 
    key = first_date_cache_key(user.id)
    first_date = cache.get(key)
    if first_date and first_date < date: 
        cache.delete(key)

def get_aggregate_generic(prefix, user, first_date, last_date): 
    key = ag_cache_key(prefix, user, first_date)
    ag = cache.get(key)
    if ag: 
        # log.debug("Aggregate CACHE HIT: %s" % ag)
        return ag
    else: 
        if user: 
            username = user.username
        else: 
            username = "_everybody"
        log.debug("Aggregate CACHE MISS: %s: %s - %s" % 
            (username, first_date, last_date))
        ag = get_aggregate_from_db(user, first_date, last_date)
        
        # # FIXME this should be done before putting the aggregates in the db
        # ag.avg_min = ag.average - ag.minimum
        # ag.max_avg = ag.maximum - ag.average
        # ag.tot_max = ag.distance - ag.maximum
        
        cache.set(key, ag)
        return ag

def get_week_aggregate(user, first_date, last_date):
    if user: 
        return get_aggregate_generic(WEEK_USER_AG_PREFIX, user, first_date, last_date) 
    else: 
        return get_aggregate_generic(WEEK_ALL_AG_PREFIX, None, first_date, last_date) 

def get_month_aggregate(user, first_date, last_date):
    if user: 
        return get_aggregate_generic(MONTH_USER_AG_PREFIX, user, first_date, last_date) 
    else: 
        return get_aggregate_generic(MONTH_ALL_AG_PREFIX, None, first_date, last_date) 


def index_last_modified_user(request, user): 
    """
    Last modification time for the index page is the max of 
    1) the last modification time for the user whose page we're loading, 
    2) the last login time for the user performing the request, and 
    3) this morning at 12am (to make sure humanized dates like "today" make sense). 
    """ 
    
    this_morning = datetime.datetime.now().replace(hour=0,minute=0,second=0)

    if user.is_anonymous():
        return this_morning
    else: 
        userid = user.id
        key = lm_cache_key(userid)
        lm = cache.get(key)
        if not lm: 
            lm = datetime.datetime.now()
            cache.set(key, lm)

        if request.user.is_authenticated():
            ll = request.user.last_login
            if ll > lm: 
                return max(this_morning, ll)

        return max(this_morning, lm)

def index_last_modified_username(request, username):
    user = User.objects.get(username=username)
    return index_last_modified_user(request, user)
    
def index_last_modified_default(request, username=None): 
    # ignore the username; we want to base decisions on the current user
    return index_last_modified_user(request, request.user)
    
def reset_last_modified(userid):
    key = lm_cache_key(userid)
    cache.delete(key)
    
def surrounding_week(start):
    last_monday = start - (ONE_DAY * start.weekday())
    sunday = start + (ONE_DAY * (6 - start.weekday()))
    return (last_monday, sunday)

def get_aggregates_by_week(user, start, scale):
    def get_previous_week(i): 
        last_monday, sunday = surrounding_week(start - i * ONE_WEEK)
        return get_week_aggregate(user, last_monday, sunday)

    return map(get_previous_week, range(scale))
    
def surrounding_month(start):
    first_of_the_month = start.replace(day=1)
    if first_of_the_month.month == 12:
         last_of_the_month = (first_of_the_month
             .replace(month=1, year=(first_of_the_month.year + 1)))
    else: 
        last_of_the_month = (first_of_the_month
            .replace(month=(first_of_the_month.month + 1)))
    last_of_the_month -= ONE_DAY
    return (first_of_the_month, last_of_the_month)
    
def get_aggregates_by_month(user, start, scale):
    def get_previous_month(i):
        quotient, remainder = divmod(((start.month - 1) - i), 12)
        newmonth = remainder + 1
        newyear = start.year + quotient
        newdate = start.replace(month=newmonth, year=newyear, day=1)
        first, last = surrounding_month(newdate)
        return get_month_aggregate(user, first, last)
    
    return map(get_previous_month, range(scale))
    
def weeks_in_range(first, last):
    delta = first - last
    weeks = delta.days / 7
    if delta.days % 7: 
        return weeks + 1
    else: 
        return weeks
        
def months_in_range(first, last):
    years = first.year - last.year
    months = first.month - last.month
    ran = (12 * years) + months + 1
    log.debug("Months in range (%s - %s): %d", last, first, ran)
    
    return ran
        
def do_splash(request): 
    return render_to_response('run/splash.html', {}, 
        context_instance=RequestContext(request))

def do_about(request): 
    return render_to_response('run/about.html', {}, 
        context_instance=RequestContext(request))


def __index_generic(request, user):
    start = datetime.datetime.now()

    today = date.today()
    if 'today' in request.GET: 
        try: 
            today = datetime.datetime.strptime(request.GET['today'], "%Y-%m-%d")
        except ValueError as e: 
            log.warn("Unable to parse date on index for user %s: %s", user, e)
    
    scale = 12
    if 'scale' in request.GET: 
        try: 
            ascale = int(request.GET['scale'])
            if ascale > 0: 
                scale = ascale
        except ValueError as e: 
            log.warn("Unable to parse scale: %s", e)

    all_weeks = get_aggregates_by_week(user, today, scale)
    all_months = get_aggregates_by_month(user, today, scale)
        
    if user: 
        username = user.username
    else: 
        username = "_everybody"

    log.debug('Index time for %s: %s', user, (datetime.datetime.now() - start))
        
    context = {'this_week': all_weeks[0],
        'last_week': all_weeks[1], 
        'all_weeks': all_weeks,
        'this_month': all_months[0], 
        'last_month': all_months[1],
        'all_months': all_months,
    }

    if not user: # i.e., all users
        sameuser = False
        has_run = "everyone's run"
        did_run = "everyone's ran"
        has_not_run = "nobody's run"
        did_not_run = "nobody's run"
    elif request.user == user:
        sameuser = True
        has_run = "you've run"
        did_run = "you ran"
        has_not_run = "you haven't run"
        did_not_run = "you didn't run"
    else:
        sameuser = False
        if user.first_name: 
            has_run = user.first_name + "'s run"
            did_run = user.first_name + " ran"
            has_not_run = user.first_name + " hasn't run"
            did_not_run = user.first_name + " didn't run"
        else:
            has_run = user.username + "'s run"
            did_run = user.username + " ran"
            has_not_run = user.username + " hasn't run"
            did_not_run = user.username + " didn't run"
    
    context['sameuser'] = sameuser
    context['has_run'] = has_run
    context['did_run'] = did_run
    context['has_not_run'] = has_not_run
    context['did_not_run'] = did_not_run
        
    return render_to_response('run/index.html', context, 
        context_instance=RequestContext(request))

@cache_control(must_revalidate=True)
def everyone(request): 
    return __index_generic(request, None)
        
@cache_control(must_revalidate=True)
@condition(etag_func=None,last_modified_func=index_last_modified_username)
def index_user(request, username):
    user = User.objects.get(username=username)
    return __index_generic(request, user)

@cache_control(must_revalidate=True)
@condition(etag_func=None,last_modified_func=index_last_modified_default)
def index(request):
    user = request.user
    if not user.is_authenticated(): 
        # return redirect_to_login(request)
        return do_splash(request)
    else: 
        return HttpResponseRedirect(reverse('run.views.index_user', 
            args=[user.username]))
    
def date_of_first_run(user):
    key = first_date_cache_key(user.id)
    date = cache.get(key)
    if not date:
        date = Run.objects.filter(user=user.id).aggregate(Min('date'))['date__min']
        log.debug("First date not in cache: %s", date)
        cache.set(key, date)
    return date
    
@cache_control(must_revalidate=True)
@condition(etag_func=None,last_modified_func=index_last_modified_username)
def all_user(request, username):
    user = User.objects.get(username=username)
    
    sameuser = (request.user == user)
    
    start = datetime.datetime.now()
    first = date_of_first_run(user)
    today = date.today()
    
    if 'today' in request.GET: 
        try: 
            today = datetime.datetime.strptime(request.GET['today'], "%Y-%m-%d")
        except ValueError as e: 
            log.warn("Unable to parse today's date: %s", e)
    
    week_scale = weeks_in_range(today, first)
    month_scale = months_in_range(today, first)

    if 'by' in request.GET and request.GET['by'] == 'week': 
        by = 'week'
        other = 'month'
        format = 'n/j/y'
        all_ags = get_aggregates_by_week(user, today, week_scale)
    elif 'by' in request.GET and request.GET['by'] == 'month': 
        by = 'month'
        other = 'week'
        format = 'n/y'
        all_ags = get_aggregates_by_month(user, today, month_scale)
    elif month_scale <= 12: 
        by = 'week'
        other = 'month'
        format = 'n/j/y'
        all_ags = get_aggregates_by_week(user, today, week_scale)
    else:
        by = 'month'
        other = 'week'
        format = 'n/y'
        all_ags = get_aggregates_by_month(user, today, month_scale)
        
    
    log.debug('Index (all) time for %s: %s', user, (datetime.datetime.now() - start))
    
    context = {'sameuser': sameuser,
        'all_ags': all_ags, 
        'by': by, 
        'other': other, 
        'format': format
    }

    return render_to_response('run/all.html', context, 
        context_instance=RequestContext(request))
    
@cache_control(must_revalidate=True)
@condition(etag_func=None,last_modified_func=index_last_modified_username)
def yield_user(request, username):
    user = User.objects.get(username=username)
    sameuser = (request.user == user)
    
    today = date.today()
    one_month = 4 * ONE_WEEK
    date_1 = today - one_month
    date_2 = today - (3 * one_month) 
    date_3 = today - (6 * one_month) 
    date_4 = today - (12 * one_month) 
    
    all_runs = Run.objects.filter(user=user.id,average_heart_rate__gt=0)
    runs_5 = all_runs.filter(date__gte=date_1)
    runs_4 = all_runs.filter(date__lt=date_1,date__gte=date_2)
    runs_3 = all_runs.filter(date__lt=date_2,date__gte=date_3)
    runs_2 = all_runs.filter(date__lt=date_3,date__gte=date_4)
    runs_1 = all_runs.filter(date__lt=date_4)
    
    context = { 'sameuser': sameuser,
        'runs_1': runs_1,
        'runs_2': runs_2,
        'runs_3': runs_3,
        'runs_4': runs_4,
        'runs_5': runs_5,
    }

    return render_to_response('run/yield.html', context, 
        context_instance=RequestContext(request))
    
def do_login(request):
    
    if request.method == "GET":
        user = request.user
        if user.is_authenticated(): 
            return HttpResponseRedirect(reverse('run.views.index_user',args=[user.username]))
        elif 'destination' in request.session:
            destination = request.session['destination']
            # log.debug('destination: %s', destination)

        return render_to_response('run/login.html', 
            context_instance=RequestContext(request))
    elif request.method == "POST": 

        if 'reset' in request.POST:
            if 'username' in request.POST: 
                request.session['resetusername'] = request.POST['username']
                
            return HttpResponseRedirect(reverse('run.views.password_reset_start'))
        else:
            username = request.POST['username']
            password = request.POST['password']

            user = authenticate(username=username, password=password)
            if user is not None:
                if user.is_active:
                    log.info("Successful login: %s", user)
                    login(request, user)
                    if 'destination' in request.session: 
                        destination = request.session['destination']
                        del request.session['destination']
                        return HttpResponseRedirect(destination)
                    else:
                        return HttpResponseRedirect(reverse('run.views.index'))
                else:
                    messages.error(request, "Login failure: user is not active.")
                    log.warning("Failed login: user %s is not active.", user)
            else: 
                messages.error(request, "Login failure: incorrect username or password.")
                log.warning("Failed login: authentication failed for %s.", username)
                return redirect_to_login(request, reset_destination=False)
    
def do_logout(request):
    if request.user.is_authenticated():
        log.info("Logout: %s", request.user)
        logout(request)
    
    return HttpResponseRedirect(reverse('run.views.index'))
    
def do_permission_denied(request):
    return HttpResponseForbidden("Sorry, you can't have that.")

def redirect_to_login(request, reset_destination=True):
    if reset_destination: 
        request.session['destination'] = request.get_full_path()
        
    return HttpResponseRedirect(reverse('run.views.do_login'))

def is_authorized(request, username=None):
    user = request.user
    if username:
        return user.is_authenticated() and user.username == username
    else:
        return user.is_authenticated()

def do_bounce(request, rest): 
    if not is_authorized(request): 
        return redirect_to_login(request)

    username = request.user.username
    return HttpResponseRedirect(("/%s/%s" % (username, rest)))

def do_bounce_default(request): 
    return do_bounce(request, "")

def do_import(request, username):
    user = request.user

    if not is_authorized(request, username): 
        return redirect_to_login(request)
    elif incomplete_profile(user):
        messages.info(request, 'You must complete your profile before importing runs.')
        return HttpResponseRedirect(reverse('run.views.userprofile_update', args=[user.username]))
    else:
        if request.method == 'POST':
            form = ImportForm(request.POST, request.FILES)
            if form.is_valid():
                erase = form.cleaned_data['erase_existing_data']
                really = form.cleaned_data['really_erase']
                runs = form.cleaned_data['data_file']
                
                log.debug("erase %s", erase)
                log.debug("really %s", really)

                # delete existing runs if the user really wants to
                if erase and really: 
                    existing = Run.objects.filter(user=user.id)
                    existing.delete()
                elif erase or really: 
                    messages.error(request, "Data not imported: should existing runs be erased?")
                    
                for run in runs: 
                    run.user = user
                    run.set_zone()
                    if not run.calories: 
                        run.set_calories()
                    log.debug("Importing run %s", run)
                    run.save()
                    
                    reset_last_modified(user.id)
                    invalidate_cache(user, run.date)
                    
                messages.success(request, "Data imported successfully.")
                return HttpResponseRedirect(reverse('run.views.userprofile', args=[user.username]))
        else:
            form = ImportForm()
    
        return render_to_response('run/import.html', {'form': form},
            context_instance=RequestContext(request))

def do_export(request, username):
    user = request.user
    if not is_authorized(request, username):
        return redirect_to_login(request)
    else:
        
        def serialize_run(run):
            return {'date' : str(run.date),
                'duration' : run.duration_in_seconds(),
                'distance' : int(run.distance_in_meters()),
                'average_heart_rate' : run.average_heart_rate,
                'calories' : run.calories}
                
        def serialize_all_runs(runs):
            acc = []
            for run in runs:
                acc.append(serialize_run(run))
            return acc
            
        return HttpResponse(json.dumps(serialize_all_runs(Run.objects.filter(user=user.id).order_by('-date'))),
            mimetype="application/json")
    
    
def password_reset_start(request):
    context = {}
    if request.method == 'GET': 
        if 'resetusername' in request.session: 
            context['username'] = request.session['resetusername']
        return render_to_response('run/reset_start.html', context,
            context_instance=RequestContext(request))

    elif request.method == 'POST': 
        if 'username' in request.POST and len(request.POST['username']) > 0: 
            username = request.POST['username']
            context['username'] = username
        else: 
            username = None

        if 'email' in request.POST and len(request.POST['email']) > 0: 
            email = request.POST['email']
            context['email'] = email
        else: 
            email = None

        if username or email: 
            try:
                if username and email:
                    user = User.objects.get(username__exact=username, email__exact=email)
                elif username: 
                    user = User.objects.get(username__exact=username)
                else: 
                    user = User.objects.get(email__exact=email)
            except User.DoesNotExist: 
                if not email:
                    messages.error(request, "User '%s' not found." % username)
                elif not username: 
                    messages.error(request, "Email address '%s' not found." % email)
                else: 
                    messages.error(request, "User '%s <%s>' not found." % (username, email))
                return render_to_response('run/reset_start.html', context, 
                    context_instance=RequestContext(request))
            
            key = str(random.randint(100000,999999))
            request.session['resetkey'] = key
    
            to_addr = user.email
            recipient_list = [to_addr]
            subject = 'Password reset request'
            short_url = reverse('run.views.password_reset_finish')
            # short_uri = request.build_absolute_uri(short_url)
            short_uri = BASE_URI + short_url
            params = urlencode({'u': user.username, 'k': key})
            full_url = short_url + '?%s' % params
            # full_uri = request.build_absolute_uri(full_url)
            full_uri = BASE_URI + full_url
            body = ('Howdy ' + user.first_name + ',\n\n' + 
                'To reset the password for user ' + user.username + 
                ' at The Runs, return to ' + short_uri +
                ' and enter the key ' + key + 
                ', or just click here: ' + full_uri)
            
            try:
                send_mail(subject, body, MAIL_FROM_ADDR, recipient_list)
                log.info("Password reset email sent for %s to %s", user, user.email)
                messages.success(request, 'An email has been sent to you with a key. ' +  
                    'Enter it below to reset your password.')
               
                return HttpResponseRedirect(reverse('run.views.password_reset_finish'))
            except Exception as e: 
                messages.error(request, "Unable to send email to: %s", to_addr)
                log.error(e)
                return render_to_response('run/reset_start.html', context, 
                    context_instance=RequestContext(request))
        else: 
            messages.error(request, "No username or email address provided.")
            return render_to_response('run/reset_start.html', context,
                context_instance=RequestContext(request))
    
def password_reset_finish(request):
    if request.method == 'GET': 
        context = {}
        if 'u' in request.GET: 
            context['username'] = request.GET['u']
        elif 'resetusername' in request.session: 
            context['username'] = request.session['resetusername']
            
        if 'k' in request.GET: 
            context['resetkey'] = request.GET['k']
            
        return render_to_response('run/reset_finish.html', context,
            context_instance=RequestContext(request))
    elif request.method == 'POST': 
        if 'username' in request.POST and len(request.POST['username']) > 0: 
            username = request.POST['username']
            
            try:
                user = User.objects.get(username__exact=username)
                submittedkey = request.POST['resetkey']
                sessionkey = request.session['resetkey']
                if submittedkey == sessionkey: 
                    newpassword1 = request.POST['newpassword1']
                    newpassword2 = request.POST['newpassword2']
                    if len(newpassword1) > 0 and newpassword1 == newpassword2:
                        user.set_password(newpassword2)
                        user.save()
                        
                        log.info("Password reset for %s", user)
                        
                        del request.session['resetusername']
                        del request.session['resetkey']
                        
                        user = authenticate(username=username, password=newpassword2)
                        if user is not None:
                            if user.is_active:
                                login(request, user)
                                return HttpResponseRedirect(reverse('run.views.index'))
                    
            except Exception as e: 
                log.error(str(e))
                return render_to_response('run/reset_finish.html', 
                    context_instance=RequestContext(request))
            else:
                return render_to_response('run/reset_finish.html', 
                    context_instance=RequestContext(request))
        else: 
            return render_to_response('run/reset_finish.html', 
                context_instance=RequestContext(request))
        
def do_signup(request):
    args = {'label': 'Are you human?'}
    CaptchaNewUserForm = create_form_subclass_with_recaptcha(NewUserForm, 
        recaptcha_client, args)
    if request.method == 'POST': 
        uform = CaptchaNewUserForm(request, request.POST)
        if uform.is_valid():
            user = uform.save()
            np2 = uform.cleaned_data['new_password2']
            user.set_password(np2)
            user.save()
            user = authenticate(username=uform.cleaned_data['username'], password=np2)
            login(request, user)
            reset_last_modified(user.id)
            
            messages.success(request, 'Your account has been created! Next, update the rest of your profile information below.')
            log.info("Created account for %s (%s)", user, user.email)
            return HttpResponseRedirect(reverse('run.views.userprofile_update', args=[user.username]))
    else: 
        uform = CaptchaNewUserForm(request)

    context = {'uform': uform}
    return render_to_response('run/signup.html', 
        context,
        context_instance=RequestContext(request))

### UserProfile ###

@cache_control(must_revalidate=True)
@condition(etag_func=None,last_modified_func=index_last_modified_default)
def userprofile(request, username):
    if not is_authorized(request, username):
        return redirect_to_login(request)

    user = request.user
    runs = Run.objects.filter(user=user.id).order_by('-date')[:5]
    shoes = (Shoe.objects.filter(user=user.id, active=True)
        .order_by('-miles')[:3])
    today = date.today()
    
    context = {'profile' : user.get_profile() }
    context['runs'] = runs
    context['shoes'] = shoes
    context['today'] = today

    return render_to_response('run/profile.html', context, 
        context_instance=RequestContext(request))
        
def userprofile_update(request, username): 
    if not is_authorized(request, username):
        return redirect_to_login(request)
    
    user = request.user
    profile = user.get_profile()
    if request.method == 'POST': 
        uform = UserForm(request.POST, instance=user)
        pform = UserProfileForm(request.POST, instance=profile)
        if uform.is_valid() and pform.is_valid():
            np2 = uform.cleaned_data['new_password2']
            if len(np2) > 0:
                user.set_password(np2)
            uform.save()
            pform.save()
            reset_last_modified(user.id)
            
            messages.success(request, "Profile updated successfully.")
            log.info("Updated profile for %s: %s", user, user.get_profile())
            return HttpResponseRedirect(reverse('run.views.userprofile',args=[user.username]))
    else: 
        uform = UserForm(instance=user)
        pform = UserProfileForm(instance=profile)

    context = {'uform': uform, 'pform': pform}
    return render_to_response('run/profile_edit.html', 
        context,
        context_instance=RequestContext(request))

def userprofile_delete(request, username): 
    if not is_authorized(request, username):
        return redirect_to_login(request)

    if request.GET['really'] == 'yes': 
        user = request.user
        log.info("Logout: %s", user)
        logout(request)
        log.info("Deleting user: %s", user)
        user.delete()

        # FIXME also need to clear out all the caches and aggregates? 

    return HttpResponseRedirect(reverse('run.views.index'))

def incomplete_profile(user):
    profile = user.get_profile()
    
    return (not ((profile.gender != None) and profile.weight and 
        profile.resting_heart_rate and profile.birthday))

### Runs ###

def page_range(page):
    maximum = page.paginator.num_pages
    lower = page.number - 5
    upper = page.number + 5
    
    if lower < 1: 
        upper = min(upper - lower, maximum)
        lower = 1

    if upper > maximum:
        lower = max(1, lower - (upper - maximum))
        upper = maximum
    
    return range(lower, upper + 1)
        
def run_all(request, username):
    if not is_authorized(request, username):
        return redirect_to_login(request)

    user = request.user
    run_list = Run.objects.filter(user=user.id).order_by('-date')
    paginator = Paginator(run_list, 10)
    page = request.GET.get('page')
    try: 
        runs = paginator.page(page)
    except (PageNotAnInteger, TypeError): 
        runs = paginator.page(1)
    except EmptyPage:
        runs = paginator.page(paginator.num_pages)
    finally: 
        context = {'range': page_range(runs), 'runs': runs}
        return render_to_response('run/run_all.html', 
            context,
            context_instance=RequestContext(request))

def run_add(request, username):
    if not is_authorized(request, username): 
        return redirect_to_login(request)

    user = request.user
    if incomplete_profile(user):
        messages.info(request, 'You must complete your profile before adding a run.')
        return HttpResponseRedirect(reverse('run.views.userprofile_update', args=[user.username]))
    else: 
        p = user.get_profile()
        s = Shoe.objects.filter(user=p.id)
        context = {'profile': p, 'shoes': s}
        return render_to_response('run/run_edit.html', 
            context,
            context_instance=RequestContext(request))
    
def run_update(request, username): 
    if not is_authorized(request, username):
        return redirect_to_login(request)
    
    run = Run()
    post = request.POST
    profile = get_object_or_404(UserProfile, pk=post['userprofile'])
    user = profile.user
    run.user = user
    
    try: 
        date = datetime.date(int(post['date_year']), 
            int(post['date_month']), int(post['date_day']))
        run.date = date
    except ValueError: 
        return render_to_response('run/run_edit.html', 
            {'profile': profile, 'error_message': 'Bad date.'}, 
            context_instance=RequestContext(request))

    try:
        if (post['duration_hours']):
            d_hours = int(post['duration_hours'])
        else: 
            d_hours = 0
            
        if (post['duration_minutes']):
            d_minutes = int(post['duration_minutes'])
        else: 
            d_minutes = 0

        if (post['duration_seconds']):
            d_seconds = int(post['duration_seconds'])
        else:
            d_seconds = 0
            
        run.set_duration(d_hours, d_minutes, d_seconds)
    except ValueError: 
        return render_to_response('run/run_edit.html', 
            {'profile': profile, 'error_message': 'Bad duration.'}, 
            context_instance=RequestContext(request))
    
    try:
        if (post['distance']):
            run.distance = post['distance']
        else: 
            return render_to_response('run/run_edit.html', 
                {'profile': profile, 'error_message': 'Distance must be set.'}, 
                context_instance=RequestContext(request))
    except ValueError: 
        return render_to_response('run/run_edit.html', 
            {'profile': profile, 'error_message': 'Bad distance.'}, 
            context_instance=RequestContext(request))

    shoe = None
    try:
        if (post['shoe']):
            shoe = Shoe.objects.get(pk=int(post['shoe']))
            # profile.last_shoe = shoe
            # shoe.miles += run.distance
            run.shoe = shoe
    except Shoe.DoesNotExist: 
        return render_to_response('run/run_edit.html', 
            {'profile': profile, 'error_message': 'Bad shoe id'}, 
            context_instance=RequestContext(request))

    try:
        if (post['average_heart_rate']):
            run.average_heart_rate = int(post['average_heart_rate'])
    except ValueError: 
        return render_to_response('run/run_edit.html', 
            {'profile': profile, 'error_message': 'Bad average heart rate.'}, 
            context_instance=RequestContext(request))
    
    run.set_calories() 
    run.set_zone()
    run.save()
    
    reset_last_modified(user.id)
    invalidate_cache(user, run.date)

    if shoe: 
        shoe.miles += Decimal(run.distance)
        profile.last_shoe = shoe
        shoe.save()
        profile.save()
        
    log.info('Added run for %s: %s', user, run)
        
    messages.success(request, "Added run " + str(run) + ".")
    
    return HttpResponseRedirect(reverse('run.views.userprofile', args=[user.username]))
    
def run_remove(request, username, run_id):
    if not is_authorized(request, username): 
        return redirect_to_login(request)
    
    user = request.user    
    run = get_object_or_404(Run, pk=run_id)
    log.info('Deleting run for %s: %s', user, run)
    run.delete()
    
    reset_last_modified(run.user.id)
    invalidate_cache(run.user, run.date)
    
    messages.success(request, "Deleted run.")

    return HttpResponseRedirect(reverse('run.views.userprofile', args=[user.username]))
    
    
### Shoes ###

def shoe_add(request, username):
    if not is_authorized(request, username): 
        return redirect_to_login(request)

    user = request.user
    if request.method == 'POST': 
        post = request.POST
        shoe = Shoe()
        shoe.user = user
        shoe.make = post['make']
        shoe.model = post['model']
        try:
            shoe.miles = int(post['miles'])
        except ValueError:
            messages.error(request, "Bad mileage.")
            return render_to_response('run/shoe_edit.html', 
                context_instance=RequestContext(request))
        shoe.active = True
        shoe.save()
        reset_last_modified(user.id)

        log.info('Added shoe for %s: %s', user, shoe)
        messages.success(request, "Shoe added.")
        return HttpResponseRedirect(reverse('run.views.userprofile', args=[user.username]))
    else:
        return render_to_response('run/shoe_edit.html', 
            context_instance=RequestContext(request))

def shoe_all(request, username):
    if not is_authorized(request, username):
        return redirect_to_login(request)

    user = request.user
    shoe_list = Shoe.objects.filter(user=user.id).order_by('-miles')
    paginator = Paginator(shoe_list, 10)

    page = request.GET.get('page')
    try: 
        shoes = paginator.page(page)
    except (PageNotAnInteger, TypeError): 
        shoes = paginator.page(1)
    except EmptyPage:
        shoes = paginator.page(paginator.num_pages)
    finally: 
        context = {'range': page_range(shoes), 'shoes': shoes}
        return render_to_response('run/shoe_all.html', 
            context, 
            context_instance=RequestContext(request))

def shoe_remove(request, username, shoe_id):
    if not is_authorized(request, username):
        return redirect_to_login(request)

    user = request.user    
    shoe = get_object_or_404(Shoe, pk=shoe_id)
    log.info('Deleting shoe for %s: %s', user, shoe)
    shoe.delete()
    reset_last_modified(shoe.user.id)
    
    messages.success(request, "Shoe deleted.")
    return HttpResponseRedirect(reverse('run.views.userprofile', args=[user.username]))
        
def shoe_toggle(request, username, shoe_id):
    if not is_authorized(request, username):
        return redirect_to_login(request)

    user = request.user
    shoe = get_object_or_404(Shoe, pk=shoe_id)
    shoe.active = not shoe.active
    shoe.save()
    reset_last_modified(shoe.user.id)
    
    log.info('Toggled shoe for %s: %s', user, shoe)
    if shoe.active: 
        messages.success(request, "Shoe activated.")
    else: 
        messages.success(request, "Shoe retired.")
    return HttpResponseRedirect(reverse('run.views.userprofile', args=[user.username]))
