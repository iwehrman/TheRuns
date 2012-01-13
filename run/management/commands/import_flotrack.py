from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from run.models import Run, Shoe, UserProfile
import json, csv, decimal
from datetime import datetime

m_in_mi = 1609.344

def Decimal(f): 
    return decimal.Decimal(str(f))

class Command(BaseCommand):
    args = '<username file.csv>'
    help = 'Imports run data exported from Flotrack as a CSV file'

    def handle(self, *args, **options):

        username = args[0]
        self.stdout.write("user: " + username + '\n')
        user = User.objects.get(username__exact=username)

        filename = args[1]
        self.stdout.write("file: " + filename + '\n')
        
        with open(filename, 'r') as file: 
            splits = filename.split('.')
            if splits[len(splits) - 1] == 'csv': 
                self.handle_csv(user, file)
            else:
                self.stdout.write("Unknown file extension: " + 
                    splits[len(splits) - 1] + '\n')
                 
    def handle_csv(self, user, file):     
        reader = csv.reader(file, dialect=csv.excel)
        for row in reader:
            try: 
                run = Run()
                run.user = user
                
                date = datetime.strptime(row[0], "%b %d, %Y")
                run.date = date
                self.stdout.write("Date: " + str(date) + ', ')
                
                minutes = int(row[1])
                seconds = int(row[2])
                d = run.set_duration(0,minutes,seconds)
                self.stdout.write("Dur: " + str(d) + ', ')
                
                distance = Decimal(float(row[3]))
                run.distance = distance
                self.stdout.write("Dist: " + str(distance) + ', ')
                
                if (row[5]):
                    hr = int(row[5])
                    run.average_heart_rate = hr
                    self.stdout.write("HR: " + str(hr) + ', ')
                    
                if (row[6]): 
                    calories = int(row[6])
                    run.calories = calories
                    self.stdout.write("Cal: " + str(calories) + ', ')
                else: 
                    run.set_calories()
                    self.stdout.write("Cal': " + str(run.calories) + ', ')
                
                run.set_zone()
                self.stdout.write("Zone: " + str(run.zone) + '\n')

                run.save()
            except ValueError:
                self.stdout.write("Skipping: " + ', '.join(row) + '\n')

        
