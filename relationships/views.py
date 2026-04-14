from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from .models import ConnectionRequest

User = get_user_model()

@login_required
def send_request(request):
    if request.user.role != 'PARENT':
        messages.error(request, 'Only parents can send connection requests.')
        return redirect('dashboard_router')
        
    if request.method == 'POST':
        child_id = request.POST.get('child_id')
        if not child_id:
            messages.error(request, 'Please provide a valid Child ID.')
            return redirect('parent_dashboard')
            
        try:
            child = User.objects.get(child_id=child_id, role='CHILD')
        except User.DoesNotExist:
            messages.error(request, 'No child found with that ID.')
            return redirect('parent_dashboard')
            
        # Check if already connected or requested
        existing_req = ConnectionRequest.objects.filter(parent=request.user, child=child).first()
        if existing_req:
            if existing_req.status == 'PENDING':
                messages.warning(request, 'A request is already pending for this child.')
            elif existing_req.status == 'ACCEPTED':
                messages.info(request, 'You are already connected to this child.')
            else:
                # Was rejected previously, let's resend
                existing_req.status = 'PENDING'
                existing_req.save()
                messages.success(request, 'Connection request sent successfully.')
        else:
            ConnectionRequest.objects.create(parent=request.user, child=child)
            messages.success(request, 'Connection request sent successfully.')
            
    return redirect('parent_dashboard')

@login_required
def respond_request(request, request_id, action):
    if request.user.role != 'CHILD':
        messages.error(request, 'Only children can respond to connection requests.')
        return redirect('dashboard_router')
        
    connection_req = get_object_or_404(
        ConnectionRequest,
        id=request_id,
        child=request.user
    )
    
    if action == 'accept':
        # ✅ Count already accepted parents
        accepted_count = ConnectionRequest.objects.filter(
            child=request.user,
            status='ACCEPTED'
        ).count()

        # ✅ Limit = 3 parents
        if accepted_count >= 3:
            messages.error(request, 'You can connect with maximum 3 parents only.')
            return redirect('child_dashboard')

        # ✅ Accept request
        connection_req.status = 'ACCEPTED'
        connection_req.save()

        messages.success(
            request,
            f'You are now connected to parent {connection_req.parent.username}.'
        )
        
    elif action == 'reject':
        connection_req.status = 'REJECTED'
        connection_req.save()
        
        messages.info(request, 'Connection request rejected.')
        
    return redirect('child_dashboard')
