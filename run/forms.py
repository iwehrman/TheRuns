from django.forms import *
from run.models import UserProfile
from django.contrib.auth.models import User

class UserProfileForm(ModelForm):
    birthday = DateField(widget=DateInput(format='%m/%d/%Y',
        attrs={'class': 'span3', 'tabindex':'8'}), 
        label='Birthdate')
        
    class Meta:
        model = UserProfile
        exclude = ('last_shoe', 'user',)
        widgets = {
            'gender': Select(attrs={'class': 'span2', 'tabindex': '6'}, 
                choices=((None, 'n/a'), (True, 'Male'), (False, 'Female'),)),
            'weight': TextInput(attrs={'class': 'span2', 'tabindex': '7'}),
            'resting_heart_rate': TextInput(attrs={'class': 'span2', 'tabindex': '9'}),
        }
        
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