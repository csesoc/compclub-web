"""
Compclub website Views.

Contains functions to render views (i.e. pages) to the user as HTTP responses.
For more information, see
https://docs.djangoproject.com/en/2.1/topics/http/views/
"""
import logging
from collections import namedtuple
from datetime import datetime, date
from smtplib import SMTPSenderRefused

from content_editor.contents import contents_for_item
from django.contrib.auth import login
from django.contrib.auth.models import Group
from django.core.mail import BadHeaderError, send_mass_mail
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import mark_safe
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic.edit import CreateView
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.http import Http404
from django.contrib.humanize.templatetags.humanize import ordinal
import calendar

from website.forms import (CreateStudentForm, CreateUserForm, EventForm,
                           RegistrationForm, VolunteerAssignForm, WorkshopForm)
from website.models import (Download, Event, LightBox, NoEmbed, Registration,
                            RichText, Workshop)
from website.plugins import cms
from website.utils import generate_status_email

logger = logging.getLogger(__name__)
DISPLAY_ERROR = "$DISPLAY_ERROR$"


class Index(ListView):
    """
    Renders the home page to the user.

    Home page shows all the basic information of the website

    Args:
        request: HTTP request header contents

    Returns:
        HTTP response containing home page

    """

    model = Event
    template_name = 'website/index.html'

    def get_context_data(self, **kwargs):
        """Return current/future events sorted by start date."""
        context = super().get_context_data(**kwargs)

        context['events_list'] = Event.objects.filter(
            highlighted_event=True,
            finish_date__gte=datetime.now()
        ) .order_by('start_date')

        return context


class EventIndex(ListView):
    """
    Render and show events page to the user.

    Events page shows list of current and future events, and how many workshops
    they consist of.

    Args:
        request: HTTP request header contents

    Returns:
        HTTP response containing events page

    """

    model = Event
    template_name = 'website/event_index.html'

    def get_context_data(self, **kwargs):
        """Return future events sorted by start date."""
        context = super().get_context_data(**kwargs)

        context['events_list'] = Event.objects \
            .filter(finish_date__gte=datetime.now()) \
            .annotate(n_workshops=Count('workshop')) \
            .order_by('start_date')

        return context


class EventPage(PermissionRequiredMixin, DetailView):
    """
    Render and show event detail page to the user.

    Event page shows specific and detailed information about a particular
    event.

    Args:
        request: HTTP request header contents
        event_id: the unique ID of the event
        slug: the human-readable event name in the URL

    Returns:
        HTTP response containing the event detail page

    """

    model = Event
    context_object_name = 'event'
    template_name = 'website/event.html'
    permission_required = ("website.view_event")
    permission_denied_message = "Event does not exist or you don't have permissions to view the event."   # noqa: E501
    unreleased_message = "Event hasn't started yet! It will be available {}{} 😄"   # noqa: E501

    def get_context_data(self, **kwargs):  # noqa: D102
        context = super().get_context_data(**kwargs)
        return context

    def get(self, request, event_id, slug):  # noqa: D102
        # check if url is valid
        event = get_object_or_404(Event, pk=event_id)

        if (event.hidden_event and not self.request.user.has_perms(
                "website.view_hidden_event")):
            self.handle_no_permission()

        if event.slug != slug:
            return redirect('website:event_page',
                            event_id=event.pk,
                            slug=event.slug)

        # Not start date yet
        if (date.today() < event.start_date and not self.request.user.has_perm(
                "website.view_unreleased_event")):
            raise Http404(
                self.get_unreleased_message().format(
                    f"from {ordinal(event.start_date.day)} ",
                    calendar.month_name[event.start_date.month]))

        # Unreleased
        if (not event.released and not self.request.user.has_perm(
                "website.view_unreleased_event")):
            raise Http404(self.get_unreleased_message().format("", "soon"))

        contents = contents_for_item(
            event, [RichText, Download, NoEmbed, LightBox])
        return render(request, self.template_name, {
            "event": event,
            "content": {
                region.key: mark_safe(
                    "".join(self._render_elements(contents[region.key])))
                for region in event.regions
            },
        })

    def _render_elements(self, elements):
        """Render django-content-editor elements."""
        for element in elements:
            if isinstance(element, RichText):
                yield cms.render_rich_text(element)
            elif isinstance(element, Download):
                yield cms.render_download(element)
            elif isinstance(element, NoEmbed):
                yield cms.render_noembed(element)
            elif isinstance(element, LightBox):
                yield cms.render_lightbox(element)

    def get_unreleased_message(self):
        """Get the unreleased event message."""
        return DISPLAY_ERROR + self.unreleased_message

    def get_permission_denied_message(self):
        """Get the permission denied message.

        This error message is only for debugging and shouldn't display since
        it provides information to unauthorized users.
        """
        return self.permission_denied_message

    def handle_no_permission(self):
        """Redirect if no permissions to view page."""
        raise Http404(self.get_permission_denied_message())


class SignUpPage(CreateView):
    """
    Render and show student sign up form to the user.

    The sign up form allows students to sign up to CompClub generally.

    Args:
        request: HTTP request header contents

    Returns:
        HTTP response containing the Sign Up form for the given event

    """

    template_name = 'registration/signup_form.html'

    def get_context_data(self, **kwargs):
        """Add both forms to context."""
        if "user_form" not in kwargs:
            kwargs["user_form"] = CreateUserForm()
        if "student_form" not in kwargs:
            kwargs["student_form"] = CreateStudentForm()
        if "student_form" not in kwargs:
            kwargs["student_form"] = CreateStudentForm()

        return kwargs

    def get(self, request, *args, **kwargs):
        """Render form."""
        return render(request, self.template_name, self.get_context_data())

    def post(self, request, *args, **kwargs):
        """Handle both form requests."""
        ctx = {}
        user_form = CreateUserForm(data=request.POST)
        student_form = CreateStudentForm(data=request.POST)

        with transaction.atomic():
            if user_form.is_valid() and student_form.is_valid():
                # Create user
                user = user_form.save()

                student_group, _existed = Group.objects.get_or_create(
                    name="default_student")
                user.groups.add(student_group)

                # Create student
                student = student_form.save(commit=False)
                student.user = user
                student.save()

                # Sign in and redirect
                login(request, user)
                return redirect('website:event_index')

        ctx["user_form"] = CreateUserForm(request.POST)
        ctx["student_form"] = CreateStudentForm(request.POST)

        return render(
            request,
            self.template_name,
            self.get_context_data(
                **ctx))


class RegistrationPage(CreateView):
    """
    Render and show event registration form to the user.

    The registration form allows students to register interest for a particular
    event.

    Args:
        request: HTTP request header contents
        event_id: the unique ID of the event
        slug: the human-readable event name in the URL

    Returns:
        HTTP response containing the registration form for the given event

    """

    form_class = RegistrationForm
    template_name = 'website/registration_form.html'
    model = Registration

    def get_context_data(self, **kwargs):  # noqa: D102
        context = super().get_context_data(**kwargs)

        event = Event.objects.get(id=self.kwargs['event_id'])
        registration_form = self.get_form()
        registration_form.fields['event'].initial = event

        context['registration_form'] = registration_form
        context['event'] = event

        return context

    def get(self, request, event_id, slug):  # noqa: D102
        # check if url is valid
        event = get_object_or_404(Event, pk=event_id)
        if event.slug != slug:
            return redirect('website:registration',
                            event_id=event.pk,
                            slug=event.slug)

        return super().get(request, event_id, slug)

    def get_success_url(self):  # noqa: D102
        return reverse('website:event_page', kwargs=self.kwargs)


class EventCreate(CreateView):
    """
    Render and show an event creation form.

    The form allows for the creation of new events. Only staff members can
    access and see this page.

    Args:
        request: HTTP request header contents

    Returns:
        HTTP response containing the event creation form

    """

    form_class = EventForm
    template_name = 'website/event_create.html'

    def get_success_url(self):  # noqa: D102
        return reverse('website:event_index', kwargs=self.kwargs)


class VolunteerStatusEmailPreview(View):
    """
    Render and show an email preview page.

    This view should be shown after assigning volunteers to workshops in an
    event. If a POST request is sent, an email will be sent to the listed
    volunteers whether they are assigned, on a waitlist or declined. Only staff
    members can access and see this page.

    Args:
        request: HTTP request header contents
        event_id: the unique ID (i.e. primary key) of the event being assigned
        slug: the human-readable event name in the URL

    Returns:
        HTTP response containing the email preview page

    """

    template_name = 'website/volunteer_status_email_preview.html'

    def get_context_data(self, event_id):  # noqa: D102
        emails = generate_status_email(event_id)
        context = {'emails': emails}
        return context

    def get(self, request, event_id, slug):  # noqa: D102
        context = self.get_context_data(event_id)
        return render(request, self.template_name, context)

    def post(self, request, event_id, slug):  # noqa: D102
        emails = self.get_context_data(event_id)['emails']
        try:
            send_mass_mail(emails)
            return redirect('website:event_index')
        except BadHeaderError as e:
            logger.exception(e)
            return HttpResponse('Invalid header found')
        except SMTPSenderRefused as e:
            logger.exception(e)
            return HttpResponse('Failed to send email. The host may not have '
                                'correctly configured the SMTP settings.')


class EventAssignVolunteers(View):
    """
    Render and show a volunteer assignment page.

    The page shows a series of forms allowing a staff member to assign
    volunteers to workshops for a particular event. Only staff members can
    access and see this page.

    Args:
        request: HTTP request header contents
        event_id: the unique ID (i.e. primary key) of the event being assigned
        slug: the human-readable event name in the URL

    Returns:
        HTTP response containing the volunteer assignment page

    """

    template_name = 'website/event_assign.html'

    def get_context_data(self, event_id):  # noqa: D102
        event = get_object_or_404(Event, pk=event_id)
        workshops = event.workshop.all().order_by('start_time')
        forms = [
            VolunteerAssignForm(initial={'workshop_id': w.id},
                                available=w.available.all(),
                                assignments=w.assignment.all())
            for w in workshops
        ]

        WorkshopTuple = namedtuple('WorkshopTuple', ['model', 'form'])
        tuples = [WorkshopTuple(w, f) for w, f in zip(workshops, forms)]
        context = {'event': event, 'workshops': tuples}

        return context

    def get(self, request, event_id, slug):  # noqa: D102
        context = self.get_context_data(event_id)

        return render(request, self.template_name, context)

    def post(self, request, event_id, slug):  # noqa: D102
        if 'workshop_id' in request.POST:
            workshop = get_object_or_404(Workshop,
                                         pk=request.POST['workshop_id'])

            post_form = VolunteerAssignForm(
                request.POST,
                available=workshop.available.all(),
                assignments=workshop.assignment.all())

            if post_form.is_valid():
                post_form.save()
                return redirect('website:assign_volunteers',
                                event_id=event_id,
                                slug=slug)


class WorkshopCreate(CreateView):
    """
    Render and show a workshop creation form page.

    The page shows a form allowing a staff member to create a new workshop for
    a particular event. Only staff members can access and see this page.

    Args:
        request: HTTP request header contents
        event_id: the ID of the event that we are making a workshop for
        slug: the human-readable event name in the URL

    Returns:
        HTTP response containing the workshop creation page

    """

    form_class = WorkshopForm
    template_name = 'website/workshop_create.html'
    model = Workshop

    def get_context_data(self, **kwargs):  # noqa: D102
        context = super().get_context_data(**kwargs)

        event = Event.objects.get(id=self.kwargs['event_id'])
        form = self.get_form()
        form.fields['event'].initial = event

        context['workshop_form'] = form
        context['event'] = event

        return context

    def get_success_url(self):  # noqa: D102
        return reverse('website:event_page', kwargs=self.kwargs)


class AboutView(TemplateView):
    """
    Render and show the about page.

    Args:
        request: HTTP request header contents

    Returns:
        HTTP response containing the about page

    """

    template_name = 'website/about.html'


# @login_required
# def user_profile(request):
#    """
#    Render and show the user's profile page. Requires that the user is logged
#    in.
#    NOTE: this is minimally implemented and is currently not used
#
#    Args:
#        request: HTTP request header contents
#
#    Returns:
#        HTTP response containing the user profile page
#    """
#    template = loader.get_template('website/profile.html')
#    return HttpResponse(template.render({}, request))
