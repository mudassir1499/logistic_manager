"""
support/views.py

The INTERNAL side of the support-ticket system — the queue that admin and
support-role users work through. The customer-facing side (creating and replying
to their own tickets) lives in the portal app under /portal/support/.

Access is gated by ``module_required('support')``: admins always pass, support-role
users pass implicitly, and staff pass only if granted the support permission.
"""

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.decorators import module_required
from settings_manager.models import CompanySettings
from utils.email_utils import send_typed_email

from .models import Ticket, TicketMessage, TicketAttachment


def notify_ticket_reply(ticket, message, to_customer):
    """
    Email a notification about a new reply.

    Args:
        ticket (Ticket): the ticket that was replied to.
        message (TicketMessage): the reply.
        to_customer (bool): True to notify the customer, False to notify the agent.
    """
    settings = CompanySettings.get_settings()
    if to_customer:
        recipient = ticket.customer.email if ticket.customer else ticket.created_by.email
        if not recipient:
            return
        send_typed_email(
            email_type='security',
            subject=f'Update on your support ticket #{ticket.id} — {settings.company_name}',
            message=(
                f"There is a new reply on your support ticket #{ticket.id} ({ticket.subject}).\n\n"
                f"{message.body}\n\n"
                f"Log in to the portal to view and reply.\n\n{settings.company_name}"
            ),
            recipient_list=[recipient],
            fail_silently=True,
        )


@module_required('support')
def queue(request):
    """The support queue: all tickets, filterable by status and assignment."""
    settings = CompanySettings.get_settings()
    status = request.GET.get('status', '')
    assignment = request.GET.get('assignment', '')
    search = request.GET.get('q', '').strip()

    tickets = Ticket.objects.select_related('customer', 'assigned_to', 'created_by')
    if status:
        tickets = tickets.filter(status=status)
    if assignment == 'mine':
        tickets = tickets.filter(assigned_to=request.user)
    elif assignment == 'unassigned':
        tickets = tickets.filter(assigned_to__isnull=True)
    if search:
        tickets = tickets.filter(
            Q(subject__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(created_by__username__icontains=search)
        )

    # Paginate so the queue stays fast and scannable as tickets pile up.
    paginator = Paginator(tickets, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    counts = {
        'open': Ticket.objects.filter(status=Ticket.STATUS_OPEN).count(),
        'pending': Ticket.objects.filter(status=Ticket.STATUS_PENDING).count(),
        'resolved': Ticket.objects.filter(status=Ticket.STATUS_RESOLVED).count(),
        'closed': Ticket.objects.filter(status=Ticket.STATUS_CLOSED).count(),
    }

    return render(request, 'support/queue.html', {
        'settings': settings,
        'tickets': page_obj,
        'page_obj': page_obj,
        'counts': counts,
        'status': status,
        'assignment': assignment,
        'search': search,
        'status_choices': Ticket.STATUS_CHOICES,
        'trail': [{'label': 'Support'}],
    })


@module_required('support')
def ticket_detail(request, ticket_id):
    """View a ticket thread and handle agent actions (reply / assign / status)."""
    settings = CompanySettings.get_settings()
    ticket = get_object_or_404(
        Ticket.objects.select_related('customer', 'assigned_to', 'created_by'), id=ticket_id
    )

    if request.method == 'POST':
        action = request.POST.get('action', 'reply')

        if action == 'reply':
            body = request.POST.get('body', '').strip()
            is_internal = request.POST.get('is_internal') == 'on'
            if body:
                msg = TicketMessage.objects.create(
                    ticket=ticket, author=request.user, body=body, is_internal=is_internal,
                )
                for f in request.FILES.getlist('attachments'):
                    TicketAttachment.objects.create(message=msg, file=f)
                # A public reply moves the ticket to "pending customer".
                if not is_internal and ticket.status == Ticket.STATUS_OPEN:
                    ticket.status = Ticket.STATUS_PENDING
                ticket.save()
                if not is_internal:
                    notify_ticket_reply(ticket, msg, to_customer=True)
                    # In-portal notification alongside the email.
                    if ticket.customer_id:
                        from accounts.services import notify_customer
                        notify_customer(
                            ticket.customer,
                            f'Support replied to your ticket #{ticket.id} ({ticket.subject}).',
                            notification_type='system',
                        )
                messages.success(request, 'Reply posted.')

        elif action == 'assign':
            assignee_id = request.POST.get('assigned_to')
            ticket.assigned_to = User.objects.filter(id=assignee_id).first() if assignee_id else None
            ticket.save(update_fields=['assigned_to', 'updated_at'])
            messages.success(request, 'Assignment updated.')

        elif action == 'status':
            new_status = request.POST.get('status')
            if new_status in dict(Ticket.STATUS_CHOICES):
                ticket.status = new_status
                ticket.save(update_fields=['status', 'updated_at'])
                from accounts.services import log_action
                log_action(request, 'ticket.status', target=f'Ticket #{ticket.id}', detail=new_status)
                messages.success(request, 'Status updated.')

        return redirect('support_ticket_detail', ticket_id=ticket.id)

    # Agents see every message including internal notes.
    thread = ticket.messages.select_related('author').prefetch_related('attachments')
    # Candidate assignees: active internal users (support/admin/staff).
    from accounts.models import Profile
    agents = User.objects.filter(
        is_active=True, profile__role__in=(Profile.ROLE_ADMIN, Profile.ROLE_STAFF, Profile.ROLE_SUPPORT)
    ).order_by('username')

    return render(request, 'support/ticket_detail.html', {
        'settings': settings,
        'ticket': ticket,
        'thread': thread,
        'agents': agents,
        'status_choices': Ticket.STATUS_CHOICES,
        'trail': [
            {'label': 'Support', 'url': reverse('support_queue')},
            {'label': f'#{ticket.id}'},
        ],
    })
