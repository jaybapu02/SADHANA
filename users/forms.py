from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User

class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'role')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # We only want to allow registering as Parent or Child, Admin is via terminal
        self.fields['role'].choices = [c for c in User.ROLE_CHOICES if c[0] in ('PARENT', 'CHILD')]
        
        # Bootstrap styling for forms
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
