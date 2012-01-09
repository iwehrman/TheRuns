from django.core.management.base import BaseCommand, CommandError
from run.models import Run

class Command(BaseCommand):
    # args = '<username file.csv>'
    help = 'Computes and sets the the \'calories\' field for runs '

    def handle(self, *args, **options):

        for run in Run.objects.all(): 
            if not run.zone:
                run.set_zone()
                run.save()
                print "Run: %s" % str(run)
                
                if run.zone:
                    print "Zone: %d" % run.zone
                else:
                    print "Zone: None"
