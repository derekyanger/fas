#!/usr/bin/python -t
__requires__ = 'TurboGears'
import pkg_resources
pkg_resources.require('CherryPy >= 2.0, < 3.0alpha')

import logging
logging.basicConfig()

import os
import sys
import getopt
import xmlrpclib
import smtplib
from email.Message import Message
import warnings

# Ignore DeprecationWarnings.  This allows us to stop getting email
# from the cron job.  We'll see the same warnings from the server starting up
warnings.simplefilter('ignore', DeprecationWarning)

import turbogears
import bugzilla
from turbogears import config
cfgfile = '/etc/export-bugzilla.cfg'
if os.access('./export-bugzilla.cfg', os.R_OK):
    cfgfile = './export-bugzilla.cfg'
turbogears.update_config(configfile=cfgfile)
from turbogears.database import session
from fas.model import BugzillaQueue

BZSERVER = config.get('bugzilla.url', 'https://bugdev.devel.redhat.com/bugzilla-cvs/xmlrpc.cgi')
BZUSER = config.get('bugzilla.username')
BZPASS = config.get('bugzilla.password')
MAILSERVER = config.get('mail.server', 'localhost')
ADMINEMAIL = config.get('mail.admin_email', 'admin@fedoraproject.org')
NOTIFYEMAIL = config.get('mail.notify_email', ['admin@fedoraproject.org'])

if __name__ == '__main__':
    opts, args = getopt.getopt(sys.argv[1:], '', ('usage', 'help'))
    if len(args) != 2 or ('--usage','') in opts or ('--help','') in opts:
        print """
    Usage: export-bugzilla.py GROUP BUGZILLA_GROUP
    """
        sys.exit(1)
    ourGroup = args[0]
    bzGroup = args[1]

    server = bugzilla.Bugzilla(url=BZSERVER, user=BZUSER, password=BZPASS,
            cookiefile=None)
    bugzilla_queue = BugzillaQueue.query.join('group').filter_by(
            name=ourGroup)

    no_bz_account = []
    for entry in bugzilla_queue:
        # Make sure we have a record for this user in bugzilla
        if entry.action == 'r':
            # Remove the user's bugzilla group
            try:
                server.updateperms(entry.email, 'rem', (bzGroup,))
            except xmlrpclib.Fault, e:
                if e.faultCode == 51:
                    # It's okay, not having this user is equivalent to setting
                    # them to not have this group.
                    pass
                else:
                    raise

        elif entry.action == 'a':
            # Make sure the user exists
            try:
                server.getuser(entry.email)
            except xmlrpclib.Fault, e:
                if e.faultCode == 51:
                    # This user doesn't have a bugzilla account yet
                    # add them to a list and we'll let them know.
                    no_bz_account.append(entry)
                    continue
                else:
                    print 'Error:', e, entry.email, entry.person.human_name
                    raise
            server.updateperms(entry.email, 'add', (bzGroup,))
        else:
            print 'Unrecognized action code: %s %s %s %s %s' % (entry.action,
                    entry.email, entry.person.human_name, entry.person.username, entry.group.name)
            continue

        # Remove them from the queue
        session.delete(entry)
        session.flush()

# Mail the people without bugzilla accounts
    if '$USER' in NOTIFYEMAIL:
        for person in no_bz_account:
            smtplib.SMTP(MAILSERVER)
            msg = Message()
            message = '''Hello %(name)s,

    As a Fedora packager, we grant you permissions to make changes to bugs in
    bugzilla to all Fedora bugs.  This lets you work together with other Fedora
    developers in an easier fashion.  However, to enable this functionality, we
    need to have your bugzilla email address stored in the Fedora Account System.
    At the moment you have:

        %(email)s

    which bugzilla is telling us is not an account in bugzilla.  If you could
    please set up an account in bugzilla with this address or change your email
    address on your Fedora Account to match an existing bugzilla account this would
    let us go forward.

    Note: this message is being generated by an automated script.  You'll continue
    getting this message until the problem is resolved.  Sorry for the
    inconvenience.

    Thank you,
    The Fedora Account System
    %(admin_email)s
    ''' % {'name': person.person.human_name, 'email': person.email,
            'admin_email': ADMINEMAIL}

            msg.add_header('To', person.email)
            msg.add_header('From', ADMINEMAIL)
            msg.add_header('Subject', 'Fedora Account System and Bugzilla Mismatch')
            msg.set_payload(message)
            smtp = smtplib.SMTP(MAILSERVER)
            smtp.sendmail(ADMINEMAIL, [person.email], msg.as_string())
            smtp.quit()
    recipients = ', '.join([e for e in NOTIFYEMAIL if e != '$USER'])
    if recipients and no_bz_account:
        smtplib.SMTP(MAILSERVER)
        msg = Message()
        people = []
        for person in no_bz_account:
            people.append('  %(user)s  --  %(name)s  --  %(email)s' %
                    {'name': person.person.human_name, 'email': person.email,
                     'user': person.person.username})
        people = '\n'.join(people)
        message = '''
The following people are in the packager group but do not have email addresses
that are valid in bugzilla:
%s

''' % people

        msg.add_header('From', ADMINEMAIL)
        msg.add_header('To', recipients)
        msg.add_header('Subject', 'Fedora Account System and Bugzilla Mismatch')
        msg.set_payload(message)
        smtp = smtplib.SMTP(MAILSERVER)
        smtp.sendmail(ADMINEMAIL, [person.email], msg.as_string())
        smtp.quit()
