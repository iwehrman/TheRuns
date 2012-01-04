import datetime, calendar
from urllib import urlencode
from datetime import date, time, timedelta
from decimal import Decimal
import random
import json

#from weakref import WeakValueDictionary

from django.http import HttpResponse, HttpResponseRedirect, HttpResponseForbidden, Http404
from django.shortcuts import render_to_response, get_object_or_404
from django.core.urlresolvers import reverse
from django.template import RequestContext
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.models import User
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.views.decorators.http import condition
from django.views.decorators.cache import cache_control
from django.core.mail import send_mail

from run.models import UserProfile, Shoe, Run, hms_to_time, Aggregate
from run.forms import UserForm, UserProfileForm

week_cache = {} #WeakValueDictionary()
month_cache = {} #WeakValueDictionary()
last_modified_cache = {}

def aggregate_runs(user, first_day, last_day):
    duration = 0
    distance = 0
    total_distance_in_meters = 0
    hr_distance_in_meters = 0
    heartbeats = 0
    calories = 0

    runs = (Run.objects.filter(user=user.id)
        .filter(date__gte=first_day).filter(date__lte=last_day))

    for run in runs: 
        duration += run.duration_in_seconds()
        distance += run.distance
        total_distance_in_meters += run.distance_in_meters()
        calories += run.calories
        if run.average_heart_rate:
            hr_distance_in_meters += run.distance_in_meters()
            heartbeats += run.heartbeats()
            
    if duration > 0: 
        speed = total_distance_in_meters / duration
    else:
        speed = 0
    
    if len(runs) > 0: 
        average = distance / len(runs)
    else: 
        average = 0
        
    ag = Aggregate()
    ag.user = user
    ag.distance = distance
    ag.average = average
    ag.pace = Run.compute_pace(duration, distance)
    ag.efficiency = Run.compute_efficiency(hr_distance_in_meters, heartbeats)
    ag.speed = speed
    ag.calories = calories
    ag.first_date = first_day
    ag.last_date = last_day
    ag.save()
        
    return ag
    
def get_aggregate_from_db(user, first_date, last_date):
    ags = Aggregate.objects.filter(user=user.id, 
        first_date=first_date, last_date=last_date)
    if len(ags) == 1:
        # print "Aggregate DB HIT: %s" % ags[0]
        return ags[0]
    elif len(ags) == 0: 
        ag = aggregate_runs(user, first_date, last_date)
        print "Aggregate DB MISS: %s" % ag
        return ag
    else: 
        raise Exception("Multiple agregates for %s at %s - %s" % 
            (user.username, first_date, last_date))
            
def invalidate_aggregates(user, date):
    ags = Aggregate.objects.filter(user=user.id,first_date__lte=date,
        last_date__gte=date)
    for ag in ags: 
        key = (user.id, ag.first_date)
        if key in week_cache: 
            print "Evicting %s from week_cache" % week_cache[key]
            del week_cache[key]
        if key in month_cache: 
            print "Evicting %s from month_cache" % month_cache[key]
            del month_cache[key]
        print "Evicting %s from DB" % ag
    ags.delete()

def get_aggregate_generic(cache, user, first_date, last_date): 
    if (user.id, first_date) in cache: 
        ag = cache[(user.id, first_date)]
        # print "Aggregate CACHE HIT: %s" % ag
        return ag
    else: 
        # print ("Aggregate CACHE MISS: %s: %s - %s" % 
        #    (user.username, first_date, last_date))
        ag = get_aggregate_from_db(user, first_date, last_date)
        cache[(user.id, first_date)] = ag
        return ag
    

def get_week_aggregate(user, first_date, last_date):
    return get_aggregate_generic(week_cache, user, first_date, last_date) 

def get_month_aggregate(user, first_date, last_date):
        return get_aggregate_generic(month_cache, user, first_date, last_date) 


def index_last_modified_user(request, user): 
    """
    Last modification time for the index page is the max of 
    1) the last modification time for the user whose page we're loading, 
    2) the last login time for the user performing the request, and 
    3) this morning at 12am (to make sure humanized dates like "today" make sense). 
    """ 
    
    this_morning = datetime.datetime.now().replace(hour=0,minute=0,second=0)
    
    userid = user.id
    if userid in last_modified_cache:
        lm = last_modified_cache[userid]
    else:
        lm = datetime.datetime.now()
        last_modified_cache[userid] = lm
      
    if request.user.is_authenticated():
        ll = request.user.last_login
        if ll > lm: 
           return max(this_morning, ll)

    return max(this_morning, lm)

def index_last_modified_username(request, username):
    user = User.objects.get(username=username)
    return index_last_modified_user(request, user)
    
def index_last_modified_default(request):
    return index_last_modified_user(request, request.user)
    
def reset_last_modified(userid):
    if userid in last_modified_cache:
        del last_modified_cache[userid]

def __index_generic(request, user):
    start = datetime.datetime.now()

    daydelta = timedelta(days=1)
    weekdelta = timedelta(weeks=1)
    weekdelta = timedelta(weeks=1)
    today = date.today()
    
    # find the the current week
    last_monday = today - (daydelta * today.weekday())
    sunday = today + (daydelta * (6 - today.weekday()))
    ag = get_week_aggregate(user, last_monday, sunday)
    all_weeks = [ag]
    
    
    # aggregate runs for the previous 11 weeks
    for i in range(11): 
        sunday = last_monday - daydelta
        last_monday = last_monday - weekdelta
        ag = get_week_aggregate(user, last_monday, sunday)
        all_weeks.append(ag)
                
    # aggregate runs for the previous 12 months
    first_of_the_month = today.replace(day=1)
    if first_of_the_month.month == 12:
         last_of_the_month = (first_of_the_month
             .replace(month=1, year=(first_of_the_month.year + 1)))
    else: 
        last_of_the_month = (first_of_the_month
            .replace(month=(first_of_the_month.month + 1)))
    last_of_the_month -= daydelta
    ag = get_month_aggregate(user, first_of_the_month, last_of_the_month)
    all_months = [ag]
    
    for i in range(11): 
        last_of_the_month = first_of_the_month - daydelta
        if first_of_the_month.month == 1: 
            first_of_the_month = (first_of_the_month
                .replace(month=12, year=(first_of_the_month.year - 1)))
        else: 
            first_of_the_month = (first_of_the_month
                .replace(month=(first_of_the_month.month - 1)))
        ag = get_month_aggregate(user, first_of_the_month, last_of_the_month)
        all_months.append(ag)
        
    # print "Duration: %s" % (datetime.datetime.now() - start)
        
    context = {'this_week': all_weeks[0],
        'last_week': all_weeks[1], 
        'all_weeks': all_weeks,
        'this_month': all_months[0], 
        'last_month': all_months[1],
        'all_months': all_months,
    }

    if request.user == user:
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
@condition(etag_func=None,last_modified_func=index_last_modified_username)
def index_user(request, username):
    user = User.objects.get(username=username)
    return __index_generic(request, user)

@cache_control(must_revalidate=True)
@condition(etag_func=None,last_modified_func=index_last_modified_default)
def index(request):
    user = request.user
    if not user.is_authenticated(): 
        return redirect_to_login(request)
    else: 
        return __index_generic(request, user)
    
def do_login(request):
    if request.method == "GET":
        if 'destination' in request.session:
            destination = request.session['destination']
            print "destination: " + destination

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
                    login(request, user)
                    if 'destination' in request.session: 
                        destination = request.session['destination']
                        del request.session['destination']
                        return HttpResponseRedirect(destination)
                    else:
                        return HttpResponseRedirect(reverse('run.views.index'))
            else: 
                return redirect_to_login(request, reset_destination=False)
    
def do_logout(request):
    if request.user.is_authenticated():
        logout(request)
    
    return HttpResponseRedirect(reverse('run.views.do_login'))
    
def do_permission_denied(request):
    return HttpResponseForbidden("Sorry, you can't have that.")

def redirect_to_login(request, reset_destination=True):
    if reset_destination: 
        request.session['destination'] = request.get_full_path()
        
    return HttpResponseRedirect(reverse('run.views.do_login'))

def export(request):
    user = request.user
    if not user.is_authenticated(): 
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
    if request.method == 'GET': 
        if 'resetusername' in request.session: 
            context = {'username': request.session['resetusername']}
        else: 
            context = {}
        return render_to_response('run/reset_start.html', context,
            context_instance=RequestContext(request))
    elif request.method == 'POST': 
        if 'username' in request.POST and len(request.POST['username']) > 0: 
            username = request.POST['username']
            request.session['resetusername'] = username
            
            try:
                user = User.objects.get(username__exact=username)
                key = str(random.randint(100000,999999))
                request.session['resetkey'] = key
                
                from_addr = 'no-reply@run.wehrman.me'
                to_addr = user.email
                recipient_list = [to_addr]
                subject = 'Password reset request'
                short_url = reverse('run.views.password_reset_finish')
                short_uri = request.build_absolute_uri(short_url)
                params = urlencode({'u': username, 'k': key})
                full_url = short_url + '?%s' % params
                full_uri = request.build_absolute_uri(full_url)
                body = ('Howdy ' + user.first_name + ',\n\n' + 
                    'To reset the password for user ' + username + 
                    ' at The Runs, return to ' + short_uri +
                    ' and enter the key ' + key + 
                    ', or just click here: ' + full_uri)
                
                send_mail(subject, body, from_addr, recipient_list)
                return HttpResponseRedirect(reverse('run.views.password_reset_finish'))
            except Exception as e: 
                print e
                return render_to_response('run/reset_start.html', 
                    context_instance=RequestContext(request))
        else: 
            return render_to_response('run/reset_start.html', 
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
                        
                        del request.session['resetusername']
                        del request.session['resetkey']
                        
                        user = authenticate(username=username, password=newpassword2)
                        if user is not None:
                            if user.is_active:
                                login(request, user)
                                return HttpResponseRedirect(reverse('run.views.index'))
                    
            except Exception as e: 
                print e
                return render_to_response('run/reset_finish.html', 
                    context_instance=RequestContext(request))
            else:
                return render_to_response('run/reset_finish.html', 
                    context_instance=RequestContext(request))
        else: 
            return render_to_response('run/reset_finish.html', 
                context_instance=RequestContext(request))
        


### UserProfile ###

@cache_control(must_revalidate=True)
@condition(etag_func=None,last_modified_func=index_last_modified_default)
def userprofile(request):
    user = request.user
    if not user.is_authenticated(): 
        return redirect_to_login(request)
    else: 
        runs = Run.objects.filter(user=user.id).order_by('-date')[:5]
        shoes = (Shoe.objects.filter(user=user.id, active=True)
            .order_by('-miles')[:3])
        today = date.today()
        
        context = {'profile' : user.get_profile() }
        context['runs'] = runs
        context['shoes'] = shoes
        context['today'] = today
        
        if request.GET.get('rundel'):
            context['info_message'] = ("Run removed.")
        elif request.GET.get('shoedel'):
            context['info_message'] = ("Shoe removed.")
        elif request.GET.get('shoeret'):
            context['info_message'] = ("Shoe retired.")


        return render_to_response('run/profile.html', context, 
            context_instance=RequestContext(request))
        
def userprofile_update(request): 
    if not request.user.is_authenticated(): 
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
            return HttpResponseRedirect(reverse('run.views.userprofile'))
    else: 
        uform = UserForm(instance=user)
        pform = UserProfileForm(instance=profile)

    context = {'uform': uform, 'pform': pform}

    return render_to_response('run/profile_edit.html', 
        context,
        context_instance=RequestContext(request))

### Runs ###
        
def run_all(request):
    user = request.user
    if not user.is_authenticated(): 
        return redirect_to_login(request)
    else: 
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
            return render_to_response('run/run_all.html', 
                {'runs': runs,},
                context_instance=RequestContext(request))

def run_new(request):
    if not request.user.is_authenticated(): 
        return redirect_to_login(request)
    
    p = request.user.get_profile()
    s = Shoe.objects.filter(user=p.id)
    context = {'profile': p, 'shoes': s}

    return render_to_response('run/run_edit.html', 
        context,
        context_instance=RequestContext(request))
    
def run_detail(request, run_id):
    if not request.user.is_authenticated(): 
        return redirect_to_login(request)
    
    return HttpResponse("Hello run %s." %  run_id)
    
def run_update(request): 
    if not request.user.is_authenticated(): 
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
        return render_to_response('run/profile.html', 
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
        return render_to_response('run/profile.html', 
            {'profile': profile, 'error_message': 'Bad duration.'}, 
            context_instance=RequestContext(request))
    
    try:
        if (post['distance']):
            run.distance = post['distance']
        else: 
            return render_to_response('run/profile.html', 
                {'profile': profile, 'error_message': 'Distance must be set.'}, 
                context_instance=RequestContext(request))
    except ValueError: 
        return render_to_response('run/profile.html', 
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
        return render_to_response('run/profile.html', 
            {'profile': profile, 'error_message': 'Bad shoe id'}, 
            context_instance=RequestContext(request))

    try:
        if (post['average_heart_rate']):
            run.average_heart_rate = int(post['average_heart_rate'])
    except ValueError: 
        return render_to_response('run/profile.html', 
            {'profile': profile, 'error_message': 'Bad average heart rate.'}, 
            context_instance=RequestContext(request))
    
    run.set_calories() 
    run.save()
    
    reset_last_modified(user.id)
    invalidate_aggregates(user, run.date)

    if shoe: 
        shoe.miles += Decimal(run.distance)
        profile.last_shoe = shoe
        shoe.save()
        profile.save()
    
    return HttpResponseRedirect(reverse('run.views.userprofile'))
    
def run_delete(request, run_id):
    run = get_object_or_404(Run, pk=run_id)
    run.delete()
    
    reset_last_modified(run.user.id)
    invalidate_aggregates(run.user, run.date)

    return HttpResponseRedirect(reverse('run.views.userprofile') + '?rundel=' + run_id)
    
    
### Shoes ###

def shoe_detail(request, shoe_id):
    if not request.user.is_authenticated(): 
        return redirect_to_login(request)

    return HttpResponse("Hello shoe %s." %  shoe_id)

def shoe_new(request):
    if not request.user.is_authenticated(): 
        return redirect_to_login(request)

    return render_to_response('run/shoe_edit.html', 
        {},
        context_instance=RequestContext(request))

def shoe_all(request):
    user = request.user
    if not user.is_authenticated(): 
        return redirect_to_login(request)
    else: 
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
            return render_to_response('run/shoe_all.html', 
                {'shoes': shoes,},
                context_instance=RequestContext(request))

def shoe_update(request): 
    user = request.user
    if not user.is_authenticated(): 
        return redirect_to_login(request)

    post = request.POST

    shoe = Shoe()
    shoe.user = user
    shoe.make = post['make']
    shoe.model = post['model']
    try:
        shoe.miles = post['miles']
    except ValueError:
        return render_to_response('run/profile.html', 
            {'error_message': 'Bad miles.'}, 
            context_instance=RequestContext(request))
    shoe.active = True
    shoe.save()
    reset_last_modified(user.id)
    return HttpResponseRedirect(reverse('run.views.userprofile'))

def shoe_delete(request, shoe_id):
    user = request.user
    if not user.is_authenticated(): 
        return redirect_to_login(request)
        
    shoe = get_object_or_404(Shoe, pk=shoe_id)
    shoe.delete()
    reset_last_modified(shoe.user.id)
    return HttpResponseRedirect(reverse('run.views.userprofile') + 
        '?shoedel=' + shoe_id)
        
def shoe_retire(request, shoe_id):
    user = request.user
    if not user.is_authenticated(): 
        return redirect_to_login(request)

    shoe = get_object_or_404(Shoe, pk=shoe_id)
    shoe.active = False
    shoe.save()
    reset_last_modified(shoe.user.id)
    return HttpResponseRedirect(reverse('run.views.userprofile') + 
        '?shoeret=' + shoe_id)
