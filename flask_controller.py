# -*- coding: utf-8 -*-
__all__ = ['user_blueprint']



import datetime

# Import Flask dependencies
from flask import (
    Blueprint, request, render_template, 
    redirect, url_for, flash, abort
)

# Import Flask-Login dependencies
from flask.ext.login import (
    login_required, login_user, logout_user, 
    confirm_login, fresh_login_required, current_user
)

# Import the resbase object from the main app module
from app import app, db, login_manager

from app.email import send_email

# Import module forms
from app.mod_user.form import *

# Import module models (i.e. UserAccount)
from app.model.user import (
    UserAccount, UserAccountSetting, UserAccountTransaction
)

# Import content limit decorator function
from app.decoratorfunc import limit_content_length

# Define the blueprint: 'login', set its url prefix: app.url/login
user_blueprint = Blueprint('user', __name__, url_prefix='')


@login_manager.user_loader
def load_user(id):
    return UserAccount.query.get(id)


def flash_errors(form):
    for field, errors in form.errors.items():
        for error in errors:
            flash(u'Greska u %s polju - %s' % (
                getattr(form, field).label.text,
                error
            ), 'alert-danger')



@user_blueprint.route('/sign-in', methods=['GET', 'POST'])
@limit_content_length(1024)
def sign_in():
    if current_user.is_authenticated():
        return redirect(url_for('product.home'))

    # If form is submitted
    form = LoginForm(request.form)
    
    # Verify form
    if form.validate_on_submit():
        user = UserAccount.query.filter_by(email=form.email.data).first()

        if user and user.check_password(form.password.data):
            login_user(user, remember=False)

            # Track user
            UserAccount.track_user(user, request)
            
            if form.next.data:
                return form.redirect(form.next.data)
                 
            return redirect(url_for('product.home'))
    
    flash_errors(form)

    return render_template('user/sign-in.html', form=form, header=True)



@user_blueprint.route('/sign-up', methods=['GET', 'POST'])
@limit_content_length(1024)
def sign_up():
    if current_user.is_authenticated():
        return redirect(url_for('product.home'))
        
    # If form is submitted
    form = RegisterForm(request.form)
    
    # Verify form
    if form.validate_on_submit():
        # create user_account
        user = UserAccount(
            email=form.email.data,
            password=form.password.data,
            confirmed=False
        )
        db.session.add(user)
        db.session.flush()

        # create user_account_setting
        ua_setting = UserAccountSetting(
            user_account_id=user.id
        )
        db.session.add(ua_setting)

        db.session.commit()

        token = user.generate_confirmation_token()
        confirm_url = url_for('user.confirm_email', token=token, _external=True, _scheme='https')
        html = render_template('user/mail-confirm.html', confirm_url=confirm_url)
        subject = 'Molimo vas da potvrdite email adresu'
        send_email(user.email, subject, html)

        login_user(user, remember=False)

        # Track user
        UserAccount.track_user(user, request)

        return redirect(url_for('product.home'))

    flash_errors(form)

    return render_template('user/sign-up.html', form=form, header=True)



@user_blueprint.route('/settings', methods=['GET', 'POST'])
@limit_content_length(1024)
@login_required
def settings():
    # If form is submitted
    form = SettingsForm(request.form)
    
    # Verify form
    if form.validate_on_submit():
        db.session.add(form.user)
        db.session.add(form.ua_setting)
        db.session.commit()

    flash_errors(form)

    return render_template('user/settings.html', form=form, header=True, footer=True)



@user_blueprint.route('/reset', methods=['GET', 'POST'])
@limit_content_length(1024)
def reset():
    # If form is submitted
    form = EmailForm(request.form)
    
    # Verify form
    if form.validate_on_submit():
        user = UserAccount.query.filter_by(email=form.email.data).first_or_404()

        token = user.generate_confirmation_token()
        confirm_url = url_for('user.reset_with_token', token=token, _external=True)
        html = render_template('user/mail-reset.html', confirm_url=confirm_url)
        subject = 'Resetovanje sifre'
        send_email(user.email, subject, html)

        return redirect(url_for('product.home'))

    flash_errors(form)

    return render_template('user/reset.html', form=form, header=True)



@user_blueprint.route('/reset/<token>', methods=['GET', 'POST'])
@limit_content_length(1024)
def reset_with_token(token):
    email = UserAccount.confirm_token(token, 10*60)
    
    if not email:
        # flash('Link potvrde je neispravan ili je isteko!', 'alert-danger')
        abort(404)

    # If form is submitted
    form = PasswordForm(request.form)

    # Verify form
    if form.validate_on_submit():
        user = UserAccount.query.filter_by(email=email).first_or_404()

        user.change_password(form.password.data)
        db.session.commit()

        return redirect(url_for('user.sign_in'))

    flash_errors(form)

    return render_template('user/reset-with-token.html', form=form, header=True, token=token)



@user_blueprint.route('/confirm/<token>', methods=['GET', 'POST'])
@limit_content_length(1024)
def confirm_email(token):
    email = UserAccount.confirm_token(token, 24*60*60)

    if not email:
        message = 'Link potvrde je neispravan ili je isteko!'
        return render_template('user/info.html', message=message)

    user = UserAccount.query.filter_by(email=email).first_or_404()

    message = 'Nalog je vec potvrđen!'

    if not user.confirmed:
        user.confirmed = True
        user.confirmed_on = datetime.datetime.now()
        db.session.add(user)
        # db.session.commit()

        ua_transaction = UserAccountTransaction(
            user_account_id=user.id,
            kind=0,
            description='Besplatan kredit za potvrdu naloga',
            credit=1000,
        )

        db.session.add(ua_transaction)
        db.session.commit()

        message = 'Potvrdili ste nalog. Hvala!'

        # if not current_user.is_authenticated():
        #     login_user(user, remember=False)

    return render_template('user/info.html', message=message)
    # return redirect(url_for('product.home'))



@user_blueprint.route('/resend-confirm', methods=['GET', 'POST'])
@limit_content_length(1024)
@login_required
def resend_confirm():
    
    # If form is submitted
    form = ResendConfirmForm(request.form)
    
    # Verify form
    if form.validate_on_submit():
        token = current_user.generate_confirmation_token()
        confirm_url = url_for('user.confirm_email', token=token, _external=True, _scheme='https')
        html = render_template('user/mail-confirm.html', confirm_url=confirm_url)
        subject = 'Molimo vas da potvrdite email adresu'
        send_email(current_user.email, subject, html)

        return redirect(url_for('product.home'))

    flash_errors(form)

    return render_template(
        'user/resend-confirm-mail.html', 
        title='Pošalji email za aktivaciju naloga',
        form=form
    )


@user_blueprint.route('/reauthentication', methods=['GET', 'POST'])
@limit_content_length(1024)
@login_required
def reauthentication():
    if request.method == 'POST':
        confirm_login()
        return redirect(url_for('product.home'))
    return render_template('user/sign-in.html')



@user_blueprint.route('/sign-out', methods=['GET'])
@limit_content_length()
@login_required
def sign_out():
    logout_user()
    return redirect(url_for('user.sign_in'))