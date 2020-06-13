"""Provides models for the CompClub website."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify

from content_editor.models import Region, create_plugin_base
from ckeditor.fields import RichTextField
from website.plugins import compressors


class CustomUser(AbstractUser):
    """
    Extension of Django user model.

    Makes email, first and last name fields compulsory.
    """

    first_name = models.CharField(max_length=200, blank=False)
    last_name = models.CharField(max_length=200, blank=False)
    email = models.EmailField(blank=False, unique=True)


class Position(models.Model):
    """Model representing the specific role of a volunteer type user."""

    name = models.CharField(verbose_name='position name', max_length=50)


class Volunteer(models.Model):
    """Model representing volunteer type users."""

    user = models.OneToOneField(get_user_model(),
                                on_delete=models.CASCADE,
                                related_name='volunteer')
    position = models.ForeignKey(Position,
                                 on_delete=models.SET_NULL,
                                 null=True,
                                 blank=True)

    def __str__(self):
        """Return a string representation of a volunteer."""
        return f"{self.user.username} ({self.user.first_name} {self.user.last_name})"  # noqa: E501


@receiver(post_save, sender=get_user_model())
def create_or_update_volunteer(sender, instance, created, **kwargs):
    """Post save hook after user/volunteer is saved."""
    if created:
        Volunteer.objects.create(user=instance)
    instance.volunteer.save()


class School(models.Model):
    """Model representing a school."""

    REGION_CHOICES = (
        ('AU_QLD', 'Queensland'),
        ('AU_NSW', 'New South Wales'),
        ('AU_SA', 'South Australia'),
        ('AU_NT', 'Northern Territory'),
        ('AU_VIC', 'Victoria'),
        ('AU_WA', 'Western Australia'),
        ('AU_TAS', 'Tasmania'),
        ('OT_NUL', 'Other - Unknown')
    )

    name = models.CharField(verbose_name='school name', max_length=50)
    region = models.CharField(verbose_name='wider govermental region',
                              max_length=6,
                              choices=REGION_CHOICES,
                              default="OT_NUL")

    def __str__(self):
        """Return a string representation of a school."""
        return self.name


class Student(models.Model):
    """Model representing a Student."""

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    school = models.ForeignKey(School, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        """Return a string representation of a student."""
        return self.user.first_name


class Event(models.Model):
    """Model representing a CompClub event."""

    name = models.CharField(max_length=100)
    start_date = models.DateField()
    finish_date = models.DateField()
    owner = models.ForeignKey(Volunteer, on_delete=models.SET_NULL, null=True)
    slug = models.SlugField(default='event',
                            unique=False,
                            help_text="The slug is the what appears in the URL. If you leave it as the default the slug will be autogenerated.")  # noqa: E501

    regions = [
        Region(key='main', title='main region')
    ]

    def __str__(self):
        """Return a string representation of an event."""
        return self.name

    def save(self, *args, **kwargs):
        """Override save to update slug."""
        self.slug = slugify(self.name)
        super(Event, self).save(*args, **kwargs)


EventPlugin = create_plugin_base(Event)


class RichText(EventPlugin):
    """Represents rich text fields."""

    text = RichTextField(blank=True)

    class Meta:   # noqa: D106
        verbose_name = 'rich text'
        verbose_name_plural = 'rich texts'


class Download(EventPlugin):
    """Represents a download field."""

    name = models.CharField(
        max_length=30,
        help_text="Try to keep this short. It appears on the download button.")
    file = models.FileField(upload_to='uploads/%Y/%m/')

    class Meta:   # noqa: D106
        verbose_name = 'download'
        verbose_name_plural = 'downloads'


class NoEmbed(EventPlugin):
    """Represents a NoEmbed field."""

    url = models.URLField(
        max_length=150,
        help_text="URL of a NoEmbed compatible URL e.g. YouTube link")
    caption = models.CharField(
        max_length=150,
        help_text="Caption that appears with the embed.")

    class Meta:   # noqa: D106
        verbose_name = 'embed'
        verbose_name_plural = 'embeds'


class LightBox(EventPlugin):
    """Represents a LightBox field."""

    file = models.ImageField(upload_to='uploads/%Y/%m/',
                             max_length=150)
    caption = models.CharField(
        max_length=150,
        help_text="Alternate text for the image.")

    class Meta:   # noqa: D106
        verbose_name = 'image'
        verbose_name_plural = 'images'

    def save(self, *args, **kwargs):  # noqa: D102
        self.file = compressors.compress_image(self.file)
        super().save(*args, **kwargs)


class Workshop(models.Model):
    """Model representing a workshop in a CompClub event."""

    event = models.ForeignKey(Event,
                              related_name='workshop',
                              on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    date = models.DateField()
    start_time = models.TimeField(verbose_name="start time")
    end_time = models.TimeField(verbose_name="end time")
    location = models.CharField(max_length=100)
    available = models.ManyToManyField(Volunteer,
                                       verbose_name='available volunteers',
                                       related_name='workshops_available')
    assigned = models.ManyToManyField(Volunteer,
                                      through='VolunteerAssignment',
                                      related_name='workshops_assigned')

    def unassigned(self):
        """Get list of available volunteers who are not yet assigned."""
        return list(self.available.exclude(id__in=self.assigned.all()))

    def withdrawn(self):
        """
        Return a list of volunteers who withdrew.

        'Withdraw' means those who were assigned or on waitlist but then
        withdrew their availability.
        """
        assignments = list(
            self.assignment.exclude(
                status=VolunteerAssignment.DECLINED).exclude(
                    volunteer__in=self.available.all()))
        return list(map(lambda assign: assign.volunteer, assignments))

    def __str__(self):
        """Return a string representation of a workshop."""
        return f"{self.event.name}: {self.name} ({self.start_time} to {self.end_time})"  # noqa: E501


class VolunteerAssignment(models.Model):
    """Model representing an assignment of a Volunteer to a Workshop."""

    workshop = models.ForeignKey(Workshop,
                                 on_delete=models.CASCADE,
                                 related_name='assignment')
    volunteer = models.ForeignKey(Volunteer,
                                  on_delete=models.CASCADE,
                                  related_name='assignment')
    ASSIGNED = 'AS'
    WAITLIST = 'WL'
    DECLINED = 'DE'
    ASSIGN_CHOICES = (
        (ASSIGNED, 'Assigned'),
        (WAITLIST, 'Waitlist'),
        (DECLINED, 'Decline'),
    )
    status = models.CharField(max_length=2, choices=ASSIGN_CHOICES)

    class Meta:  # noqa: D106
        unique_together = ('workshop', 'volunteer')

    def __str__(self):  # noqa: D105
        status_msg = self.status
        if self.status == VolunteerAssignment.ASSIGNED:
            status_msg = 'assigned to'
        elif self.status == VolunteerAssignment.WAITLIST:
            status_msg = 'on waitlist for'
        elif self.status == VolunteerAssignment.DECLINED:
            status_msg = 'declined for'

        return f'{self.volunteer} -- {status_msg} -- {self.workshop}'


class Registration(models.Model):
    """Model representing a student registration."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    email = models.EmailField(verbose_name='email address')
    number = models.CharField(verbose_name='phone number', max_length=15)
    date_of_birth = models.DateField()
    parent_email = models.EmailField()
    parent_number = models.CharField(verbose_name='parent\'s phone number',
                                     max_length=15)

    def __str__(self):
        """Return a string representation of a registration."""
        return f"{self.name}"
