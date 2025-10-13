from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from app.cashier import cashier
from app.models import db, User, UserRole, CashierPin
from app.auth.decorators import login_required_with_role


@cashier.route('/settings')
@login_required_with_role(UserRole.CASHIER)
def settings():
    """Cashier settings page"""
    # Get current cashier's PIN status
    cashier_pin = CashierPin.query.filter_by(
        cashier_id=current_user.id,
        branch_id=current_user.branch_id,
        is_active=True
    ).first()
    
    has_pin = cashier_pin is not None
    
    return render_template('cashier/settings.html', has_pin=has_pin)


@cashier.route('/set_pin', methods=['POST'])
@login_required_with_role(UserRole.CASHIER)
def set_pin():
    """Set or update cashier PIN code"""
    try:
        data = request.get_json()
        new_pin = data.get('new_pin', '').strip()
        confirm_pin = data.get('confirm_pin', '').strip()
        
        # Validate PIN format
        if not new_pin or len(new_pin) != 4 or not new_pin.isdigit():
            return jsonify({
                'success': False,
                'message': 'PIN must be exactly 4 digits'
            })
        
        # Validate PIN confirmation
        if new_pin != confirm_pin:
            return jsonify({
                'success': False,
                'message': 'PIN confirmation does not match'
            })
        
        # Check if cashier already has a PIN
        cashier_pin = CashierPin.query.filter_by(
            cashier_id=current_user.id,
            branch_id=current_user.branch_id
        ).first()
        
        if cashier_pin:
            # Update existing PIN
            cashier_pin.set_pin(new_pin)
            cashier_pin.is_active = True
            message = 'PIN updated successfully'
        else:
            # Create new PIN
            cashier_pin = CashierPin(
                cashier_id=current_user.id,
                branch_id=current_user.branch_id,
                is_active=True
            )
            cashier_pin.set_pin(new_pin)
            db.session.add(cashier_pin)
            message = 'PIN created successfully'
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': message
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error setting PIN: {str(e)}'
        })


@cashier.route('/verify_current_pin', methods=['POST'])
@login_required_with_role(UserRole.CASHIER)
def verify_current_pin():
    """Verify current PIN before allowing changes"""
    try:
        data = request.get_json()
        current_pin = data.get('current_pin', '').strip()
        
        if not current_pin or len(current_pin) != 4 or not current_pin.isdigit():
            return jsonify({
                'success': False,
                'message': 'Invalid PIN format'
            })
        
        # Verify current PIN
        is_valid = CashierPin.verify_cashier_pin(
            cashier_id=current_user.id,
            branch_id=current_user.branch_id,
            pin_code=current_pin
        )
        
        if is_valid:
            return jsonify({
                'success': True,
                'message': 'Current PIN verified'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Invalid current PIN'
            })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error verifying PIN: {str(e)}'
        })


@cashier.route('/change_pin', methods=['POST'])
@login_required_with_role(UserRole.CASHIER)
def change_pin():
    """Change cashier PIN code after verifying current PIN"""
    try:
        data = request.get_json()
        current_pin = data.get('current_pin', '').strip()
        new_pin = data.get('new_pin', '').strip()
        confirm_pin = data.get('confirm_pin', '').strip()
        
        # Validate current PIN
        if not current_pin or len(current_pin) != 4 or not current_pin.isdigit():
            return jsonify({
                'success': False,
                'message': 'Invalid current PIN format'
            })
        
        # Validate new PIN format
        if not new_pin or len(new_pin) != 4 or not new_pin.isdigit():
            return jsonify({
                'success': False,
                'message': 'New PIN must be exactly 4 digits'
            })
        
        # Validate PIN confirmation
        if new_pin != confirm_pin:
            return jsonify({
                'success': False,
                'message': 'New PIN confirmation does not match'
            })
        
        # Verify current PIN
        is_valid = CashierPin.verify_cashier_pin(
            cashier_id=current_user.id,
            branch_id=current_user.branch_id,
            pin_code=current_pin
        )
        
        if not is_valid:
            return jsonify({
                'success': False,
                'message': 'Invalid current PIN'
            })
        
        # Update PIN
        cashier_pin = CashierPin.query.filter_by(
            cashier_id=current_user.id,
            branch_id=current_user.branch_id
        ).first()
        
        if cashier_pin:
            cashier_pin.set_pin(new_pin)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'PIN changed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No existing PIN found'
            })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error changing PIN: {str(e)}'
        })


@cashier.route('/disable_pin', methods=['POST'])
@login_required_with_role(UserRole.CASHIER)
def disable_pin():
    """Disable cashier PIN code after verification"""
    try:
        data = request.get_json()
        current_pin = data.get('current_pin', '').strip()
        
        if not current_pin or len(current_pin) != 4 or not current_pin.isdigit():
            return jsonify({
                'success': False,
                'message': 'Invalid PIN format'
            })
        
        # Verify current PIN
        is_valid = CashierPin.verify_cashier_pin(
            cashier_id=current_user.id,
            branch_id=current_user.branch_id,
            pin_code=current_pin
        )
        
        if not is_valid:
            return jsonify({
                'success': False,
                'message': 'Invalid current PIN'
            })
        
        # Disable PIN
        cashier_pin = CashierPin.query.filter_by(
            cashier_id=current_user.id,
            branch_id=current_user.branch_id
        ).first()
        
        if cashier_pin:
            cashier_pin.is_active = False
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'PIN disabled successfully'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No PIN found to disable'
            })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error disabling PIN: {str(e)}'
        })
