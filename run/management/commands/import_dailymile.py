from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from fit.run.models import Run, Shoe, UserProfile
import json, csv
from datetime import datetime

m_in_mi = 1609.344

class Command(BaseCommand):
    args = '<username file.csv>'
    help = 'Imports run data exported from DailyMile as a CVS file'

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
            elif splits[len(splits) - 1] == 'json': 
                self.handle_json(user, file)
            else:
                self.stdout.write("Unknown file extension: " + 
                    splits[len(splits) - 1] + '\n')
        
    def handle_json(self, user, file):
        for line in file: 
            try:
                obj = json.loads(line)
                self.stdout.write(str(obj) + '\n')
            
                if obj[u'workout_type'] == u'Running': 
                    run = Run()
                    run.user = user

                    date = datetime.strptime(obj[u'date'], "%m/%d/%y")
                    self.stdout.write("Date: " + str(date) + ', ')
                    run.date = date
                    
                    distance = float(obj[u'distance'])
                    self.stdout.write("Distance: " + str(distance) + ', ')
                    run.distance = distance
                    
                    duration_in_secs = int(obj[u'duration'])
                    duration = run.set_duration(0,0,duration_in_secs)
                    self.stdout.write("Duration: " + str(duration) + ', ')
                    
                    if not obj[u'hr_avg'] == None: 
                        heart_rate = int(obj[u'hr_avg'])
                        run.average_heart_rate = heart_rate
                        self.stdout.write("HR: " + str(heart_rate) + ', ')
                    self.stdout.write('\n')
                    
                    run.save()
            except: 
                 print "Skipping line: " + line            
            
    def handle_csv(self, user, file):     
        reader = csv.reader(file, dialect=csv.excel)
        for row in reader:
            if row[1] == "Running": 
                try: 
                    run = Run()
                    run.user = user
                    
                    date = datetime.strptime(row[0], "%m/%d/%Y")
                    run.date = date
                    self.stdout.write("Date: " + str(date) + ', ')
                    
                    distance = float(row[2]) / m_in_mi
                    run.distance = distance
                    self.stdout.write("Dist: " + str(distance) + ', ')
                    
                    duration = int(row[3])
                    d = run.set_duration(0,0,duration)
                    self.stdout.write("Dur: " + str(d) + '\n')

                    run.save()
                except ValueError:
                    self.stdout.write("Skipping: " + ', '.join(row) + '\n')

        
