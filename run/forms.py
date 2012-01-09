import datetime, logging, json

from django.contrib.auth.models import User
from django.forms import *

from run.models import UserProfile, Run, hms_to_time

log = logging.getLogger(__name__)

class UserProfileForm(ModelForm):
    birthday = DateField(widget=DateInput(format='%m/%d/%Y',
        attrs={'class': 'span3', 'tabindex':'8'}), 
        label='Birthdate')
    
    gender = NullBooleanField(widget=Select(attrs={'class': 'span2', 'tabindex': '6'}, 
        choices=((None, ''), (True, 'Male'), (False, 'Female'),)),
        label='Sex')
            
    weight = CharField(widget=TextInput(attrs={'class': 'span2', 'tabindex': '7'}),
        label='Weight (lbs)')
        
    resting_heart_rate = CharField(TextInput(attrs={'class': 'span2', 'tabindex': '9'}),
        label='Resting heart rate (b/min)')
        
    class Meta:
        model = UserProfile
        exclude = ('last_shoe', 'user',)
        
class UserForm(ModelForm): 
    
    new_password1 = CharField(required=False,label='New password?',
        widget=PasswordInput(attrs={'tabindex':'4'}))
    new_password2 = CharField(required=False,label='(repeat)',
        widget=PasswordInput(attrs={'tabindex':'5'}))
        
    def clean_new_password2(self):
        np1 = self.cleaned_data['new_password1']
        np2 = self.cleaned_data['new_password2']
        if np1 != np2:
            raise forms.ValidationError("Password fields do not match.")
        if len(np2) > 0 and len(np2) < 6:
            raise forms.ValidationError("Password must be at least 6 characters long.")

        return np2
    
    class Meta: 
        model = User
        widgets = {'first_name': TextInput(attrs={'tabindex':'1'}),
            'last_name': TextInput(attrs={'tabindex':'2'}),
            'email': TextInput(attrs={'tabindex':'3'}),
            }
        exclude = ['username', 'password', 'is_staff', 'is_active', 
            'is_superuser', 'last_login', 'date_joined', 'groups', 
            'user_permissions']



def obj_to_run(obj):
    
    _date = u'date'
    _duration = u'duration'
    _average_heart_rate = u'average_heart_rate'
    _calories = u'calories'
    _distance = u'distance'
    
    run = Run()
    
    # try to parse date field
    run.date = datetime.datetime.strptime(obj[_date], "%Y-%m-%d") 

    # try to parse the duration and distance fields
    run.duration = hms_to_time(0,0,int(obj[_duration]))
    run.distance = float(obj[_distance]) / 1609.344

    # try to parse the HR and calories fields, which may be null
    if obj[_average_heart_rate]: 
        run.average_heart_rate = int(obj[_average_heart_rate])
    if obj[_calories]: 
        run.calories = int(obj[_calories])
    return run

class ImportForm(Form):
    
    class ImportableFileField(FileField):
        
        def to_python(self, data_file):

            data_file.open()
            line = ''.join(data_file.read())

            try:
                json_objs = json.loads(line)
                return [obj_to_run(obj) for obj in json_objs]

            except Exception as e:
                            log.info("ValidationError: %s", str(e))
                            raise ValidationError("Unable to parse JSON file. Error: %s." % str(e))

    
    data_file = ImportableFileField(widget=FileInput(attrs={'tabindex': '1'}),
        label='Data file')
    erase_existing_data = BooleanField(widget=CheckboxInput(attrs={'tabindex': '2'}),
        required=False,label='Erase existing?')
    really_erase = BooleanField(widget=CheckboxInput(attrs={'tabindex': '3'}),
        required=False,label='Really erase?')
    