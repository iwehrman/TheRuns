import datetime, logging, json

from django.contrib.auth.models import User
from django.forms import *
from run.models import UserProfile, Run, hms_to_time

log = logging.getLogger(__name__)

class UserProfileForm(ModelForm):
    birthday = DateField(widget=DateInput(format='%m/%d/%Y',
        attrs={'class': 'span3', 'tabindex':'8', 'placeholder': '01/31/1970'}), 
        label='Birthdate')
    
    gender = NullBooleanField(widget=Select(attrs={'class': 'span2', 'tabindex': '6'}, 
        choices=((None, ''), (True, 'Male'), (False, 'Female'),)),
        label='Sex')
            
    weight = CharField(widget=TextInput(attrs={'class': 'span2', 'tabindex': '7', 'placeholder': '123'}),
        label='Weight (lbs)')
        
    resting_heart_rate = CharField(widget=TextInput(attrs={'class': 'span2', 'tabindex': '9', 'placeholder': '75'}),
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

class NewUserForm(ModelForm): 
    
    new_password1 = CharField(required=False,label='Password',
        widget=PasswordInput(attrs={'tabindex':'5'}, render_value=True))
    new_password2 = CharField(required=False,label='Password (again)',
        widget=PasswordInput(attrs={'tabindex':'6'}, render_value=True))
        
    def clean_username(self): 
        username = self.cleaned_data['username']

        if username == '': 
            raise forms.ValidationError("Username must not be empty.")
        elif username[0] == '_': 
            raise forms.ValidationError("Username must not begin with an underscore.")

        try: 
            user = User.objects.get(username=username)
            # a user with this username already exists; raise an exception. 
            raise forms.ValidationError("Username %s is already in use.", username)
        except: 
            # a user with username was not found; all is well. 
            return username

    def clean_email(self): 
        email = self.cleaned_data['email']
        try: 
            user = User.objects.get(email=email)
            # a user with this email address already exists; raise an exception. 
            raise forms.ValidationError("Email address %s is already in use.", email)
        except: 
            # a user with email address was not found; all is well. 
            return email

    def clean_new_password2(self):
        np1 = self.cleaned_data['new_password1']
        np2 = self.cleaned_data['new_password2']
        if np1 != np2:
            raise forms.ValidationError("Password fields do not match.")
        if len(np2) < 6:
            raise forms.ValidationError("Password must be at least 6 characters long.")

        return np2
    
    class Meta: 
        model = User
        widgets = {'username': TextInput(attrs={'tabindex':'1'}),
            'first_name': TextInput(attrs={'tabindex':'2'}),
            'last_name': TextInput(attrs={'tabindex':'3'}),
            'email': TextInput(attrs={'tabindex':'4'}),
            }
        exclude = ['password', 'is_staff', 'is_active', 
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
    run.date = datetime.datetime.strptime(obj[_date], "%Y-%m-%d").date()

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
    
