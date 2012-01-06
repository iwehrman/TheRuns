from django.db import models
from django.db.models.signals import post_save, pre_save, pre_delete
from django.contrib.auth.models import User
from django.dispatch import receiver
import decimal
from decimal import getcontext
from datetime import date, datetime, time

def Decimal(f): 
    return decimal.Decimal(str(f))

meters_per_mile = Decimal(1609.344)
kg_per_pound = Decimal(0.45359237)
cal_per_joule = Decimal(0.239005736)

class Shoe(models.Model):
    user = models.ForeignKey(User)
    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    miles = models.DecimalField(max_digits=5, decimal_places=2)
    active = models.BooleanField(default=True)

    def __unicode__(self):
        return self.make + " " + self.model + " (" + str(self.miles) + ")"

class UserProfile(models.Model):
    user = models.OneToOneField(User)
    gender = models.NullBooleanField()
    weight = models.PositiveIntegerField(blank=True, null=True)
    birthday = models.DateField(blank=True, null=True)
    last_shoe = models.ForeignKey(Shoe,blank=True, null=True, 
        on_delete=models.SET_NULL)
    resting_heart_rate = models.PositiveIntegerField(blank=True, null=True)
        
    def __unicode__(self):
        return ("(gender: " + str(self.gender) + ", weight: " + str(self.weight) + 
            ", birthday: " + str(self.birthday) + ", HR: " + str(self.resting_heart_rate) + 
            ", last_shoe: " + str(self.last_shoe) + ")")
        
    def maximum_heart_rate(self):
        return 205.8 - (0.685 * float(self.age_in_years()))

    def age_in_years(self): 
        td = date.today() - self.birthday
        total_seconds = td.seconds + (3600 * 24 * td.days)
        seconds_in_year = 3600 * 24 * 365
        return int(total_seconds // seconds_in_year)
    
    def weight_in_kg(self):
        return Decimal(self.weight) * kg_per_pound

    def vO2max(self):
        return (15.0 * 
            (self.maximum_heart_rate() / float(self.resting_heart_rate)))        
    
class Run(models.Model):
    user = models.ForeignKey(User) 
    shoe = models.ForeignKey(Shoe, blank=True, null=True, 
        on_delete=models.SET_NULL)
    date = models.DateField()
    duration = models.TimeField()
    distance = models.DecimalField(max_digits=5, decimal_places=2)
    average_heart_rate = models.IntegerField(blank=True, null=True) 
    calories = models.IntegerField(blank=True, null=True)

    def __unicode__(self):
        return str(self.distance) + " miles on " + str(self.date)

    def heart_rate_percent(self):
        maxhr = self.user.get_profile().maximum_heart_rate()
        if maxhr and self.average_heart_rate:
            return 100.0 * (self.average_heart_rate / maxhr)
        else:
            None

    def duration_as_datetime(self):
        return datetime.combine(datetime.today(), self.duration)
        
    def duration_as_string(self):
        return formatted_time(self.duration)

    def duration_in_seconds(self):
        t = self.duration
        return (3600 * t.hour) + (60 * t.minute) + t.second
        
    def set_duration(self, hours, minutes, seconds):
        d = hms_to_time(hours, minutes, seconds)
        self.duration = d
        return d
    
    @staticmethod    
    def compute_pace(duration_in_seconds, distance):
        if distance > 0:
            pace = duration_in_seconds / distance
            return formatted_time(hms_to_time(0, 0, pace))
        else:
            return None
        
    def pace(self):
        return Run.compute_pace(self.duration_in_seconds(), self.distance)
        
    def heartbeats(self):
        return (Decimal(self.average_heart_rate) * 
            (Decimal(self.duration_in_seconds()) / 60))
        
    def distance_in_meters(self):
        return self.distance * meters_per_mile
        
    @staticmethod
    def compute_efficiency(distance_in_meters, heartbeats):
        if heartbeats > 0:
            return distance_in_meters / heartbeats
        else: 
            return 0
                    
    def efficiency(self):
        """
        Distance per effort (times a constant for readability)
        """
        if self.average_heart_rate:
            return Run.compute_efficiency(self.distance_in_meters(), 
                self.heartbeats())
        else: 
            return 0
    
    @staticmethod
    def compute_calories_per_sec(hr, is_male, weight, age, vO2max=None):
        if vO2max: 
            EE = Decimal(-59.3954)
            if is_male: 
                EE += Decimal(-36.3781)
                EE += (Decimal(0.217) * Decimal(age))
                EE += (Decimal(0.634) * Decimal(hr))
                EE += (Decimal(0.394) * Decimal(weight))
                EE += (Decimal(0.404) * Decimal(vO2max))
            elif is_male == False: 
                EE += (Decimal(0.450) * Decimal(hr)) 
                EE += (Decimal(0.103) * Decimal(weight)) 
                EE += (Decimal(0.274) * Decimal(age))
                EE += (Decimal(0.380) * Decimal(vO2max))
            else: 
                raise Exception("Gender must be set for calorie count")
        else: 
            if is_male: 
                EE = Decimal(-55.0969)
                EE += (Decimal(0.6309) * Decimal(hr))
                EE += (Decimal(0.1988) * Decimal(weight))
                EE += (Decimal(0.2017) * Decimal(age))
            elif is_male == False: 
                EE = Decimal(-20.4022)
                EE += (Decimal(0.4472) * Decimal(hr)) 
                EE -= (Decimal(0.1263) * Decimal(weight)) 
                EE += (Decimal(0.074) * Decimal(age))
            else: 
                raise Exception("Gender must be set for calorie count")
            
        EE *= cal_per_joule   
        EE /= Decimal(60.0)
        
        return EE 
    
    def set_calories(self):
        profile = self.user.get_profile()
        
        hr = self.average_heart_rate
        gender = profile.gender
        weight_in_lbs = profile.weight
        weight_in_kg = profile.weight_in_kg()
        age = profile.age_in_years()
        
        if hr and (gender is not None) and weight_in_kg and age: 
            if profile.resting_heart_rate:
                vO2max = profile.vO2max()
                rate = Run.compute_calories_per_sec(hr, gender, weight_in_kg, age, vO2max)
            else: 
                rate = Run.compute_calories_per_sec(hr, gender, weight_in_kg, age)
            self.calories = int(rate * self.duration_in_seconds())
        elif (not hr) and weight_in_lbs: 
            self.calories = int(float(weight_in_lbs) * 0.75 * float(self.distance))
        else: 
            self.calories = 0

def formatted_time(t):
    if t.hour > 0: 
        output = str(t.hour) + ':'
    else:
        output = ''
    
    return output + t.strftime("%M:%S")
    
        
def hms_to_time(hours, minutes, seconds):
    """
    Returns a time object that represents a duration specified with 
    potentially "improper" times (e.g., minutes > 59).  The duration must not 
    exceed 1 day.
    """
    d = time(0,0,0,0)

    if seconds < 60: 
        d = d.replace(second=seconds)
    else: 
        d = d.replace(second=seconds % 60)
        minutes += (seconds // 60)
         
    if minutes < 60: 
        d = d.replace(minute=minutes)
    else: 
        d = d.replace(minute=minutes % 60)
        hours += (minutes // 60)
         
    if hours < 24: 
        d = d.replace(hour=hours)
    else: 
        raise Exception("Duration must not exceed 1 day")

    return d

# @receiver(post_save, sender=Run)
# def update_on_run_save(sender, **kwargs):
#     """
#     Automagically update the UserProfile.last_shoe and Shoe.miles properties. 
#     """
#     run = kwargs['instance']
#     created = kwargs['created']
#     shoe = run.shoe
#     if shoe and created:
#         print "Updating shoe miles" 
#         shoe.miles += Decimal(run.distance)
#         print "New miles " + str(shoe.miles)
#         profile = run.user.get_profile()
#         profile.last_shoe = shoe
#         shoe.save()
#         profile.save()
        
@receiver(pre_delete, sender=Run)
def update_on_run_delete(sender, **kwargs):
    """
    Automagically update the Shoe.miles propertie. 
    """
    run = kwargs['instance']
    shoe = run.shoe
    if shoe:
        print "Deleting shoe miles" 
        shoe.miles -= Decimal(run.distance)
        print "New miles " + str(shoe.miles)
        shoe.save()

@receiver(pre_delete, sender=Shoe)
def update_on_shoe_delete(sender, **kwargs):
    shoe = kwargs['instance']
    if shoe: 
        profile = shoe.user.get_profile()
        if shoe.id == profile.last_shoe.id: 
            profile.last_shoe = None
            profile.save()
            
def create_user_profile(sender, instance, created, **kwargs):
    """
    Automatically create a new UserProfile for every User
    """
    
    if created: 
        UserProfile.objects.create(user=instance, birthday=date.today())

post_save.connect(create_user_profile, sender=User)

class Aggregate(models.Model):
    user = models.ForeignKey(User)
    first_date = models.DateField()
    last_date = models.DateField()
    pace = models.CharField(max_length=10,blank=True, null=True)
    calories = models.PositiveIntegerField()
    distance = models.DecimalField(max_digits=9,decimal_places=3)
    average = models.DecimalField(max_digits=9,decimal_places=3)
    speed = models.DecimalField(max_digits=5,decimal_places=3)
    efficiency = models.DecimalField(max_digits=5,decimal_places=3)
    
        
    def __unicode__(self):
        return "%s: %s - %s" % (self.user.username, self.first_date, self.last_date)
    
    