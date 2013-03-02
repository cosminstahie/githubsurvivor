import os
from datetime import datetime
from itertools import islice
from random import shuffle

from flask import Flask, render_template, request
from jinja2 import FileSystemLoader

import survivor
from survivor import reporting, timeutils, config
from survivor.models import User, Issue
from survivor.web import template

app = Flask(__name__, static_url_path='')

def request_arg(key, default=None):
    try: return request.args[key]
    except KeyError: return default

reporting_period_fns = {'week': reporting.weekly_reporting_period,
                        'sprint': reporting.sprint_reporting_period,
                        'month': reporting.monthly_reporting_period}

def reporting_period(unit, anchor, offset=0):
    """
    Returns the start and end dates of a reporting period.

    `unit` is a string like 'week', 'sprint', 'month'
    `anchor` is any date within the reporting period
    `offset` is an integer to offset the window by
    """
    try: calculate_period = reporting_period_fns[unit]
    except KeyError: calculate_period = reporting_period_fns['week']
    return calculate_period(anchor, offset)

### Dashboard

@app.route('/')
def dashboard():
    # Get filters from URL
    #TODO: Remove default milestone
    milestone = request.args.get('milestone','SecondMilestone')
    label_name = request.args.get('label')

    today = timeutils.today()

    reporting_unit = request_arg('reporting_unit', default=config['reporting.window'])
    previous_periods = int(request_arg('previous_periods', default=12))

    reporting_periods = [reporting_period(reporting_unit, today, -i)
                         for i in reversed(xrange(previous_periods))]
    current_period = reporting_periods[-1]

    developers = User.objects.competitors()
    # Randomise order of developers with equal bug counts
    # FIXME: show developers as tied in template
    shuffle(developers)

    closed_issues = lambda u: u.closed_issues().closed_in(current_period.start, current_period.end)
    if milestone:
        num_closed = lambda u: len(closed_issues(u).filter(milestone=milestone))
    elif label_name:
        num_closed = lambda u: len(closed_issues(u).filter(labels__contains=label_name))
    else:
        num_closed = lambda u: len(closed_issues(u))

    # Rank from lowest number of closed bugs to highest
    ranked = sorted(((dev, num_closed(dev)) for dev in developers),
                    key=lambda pair: pair[1])

    # FIXME: this needs some work.
    # This currently makes 3 * previous_periods (i.e. 36) separate Mongo queries

    # Create an annonymous function that returns a fresh query set of filtered
    # issue every time it's called
    filter_issues = lambda: Issue.objects.filter(milestone=milestone,
                                                 labels__contains=label_name)

    # Number of bugs opened/closed in each period
    opened_closed_bugs = []
    for period in reporting_periods:
      opened_closed_bugs.append({'period': period,
                                 'opened': len(filter_issues().opened_in(period.start, period.end)),
                                 'closed': len(filter_issues().closed_in(period.start, period.end))})

    # Point-in-time open bug count
    open_bugs = []
    for period in reporting_periods:
      open_bugs.append({'period': period,
                        'count': len(filter_issues().open_at(period.end))})

    # Close rate
    current_close_rate = opened_closed_bugs[-1]['closed'] - opened_closed_bugs[-1]['opened']
    previous_close_rate = opened_closed_bugs[-2]['closed'] - opened_closed_bugs[-2]['opened']
    close_rate_delta = abs(int(float(current_close_rate) / float(previous_close_rate) * 100)) \
        if previous_close_rate else float('inf')

    return render_template('dashboard.jinja2',
                           # Context vars
                           today=today,
                           period_label=reporting_unit,
                           milestones=Issue.objects.milestones(),
                           labels=Issue.objects.labels(),
                           ranked=ranked,
                           opened_closed_bugs=opened_closed_bugs,
                           open_bugs=open_bugs,
                           open_bug_count=open_bugs[-1]['count'],
                           prev_open_bug_count=open_bugs[-2]['count'])

### Old bugs

@app.route('/old-bugs')
def old_bugs():
    "Display issues opened before some date."
    request_date = request_arg('opened-before')
    threshold = timeutils.with_local_tz(datetime.strptime(request_date, '%Y-%m-%d')) if request_date \
        else reporting.sprint_reporting_period(timeutils.today()).start

    issues = Issue.objects.older_than(threshold).order_by('-opened')

    return render_template('old-issues.jinja2', date=threshold, issues=issues)

### Workload

@app.route('/workload')
def workload():
    "Display number of issues assigned to each developer."
    workload = ((dev, len(dev.assigned_issues())) for dev in User.objects.developers())
    return render_template('workload.jinja2', workload=workload)

### Unassigned bugs

@app.route('/unassigned')
def unassigned():
    "Display all unassigned bugs."
    issues = Issue.objects.unassigned()
    return render_template('unassigned.jinja2', issues=issues)

### Initialisation

if __name__ == "__main__":
    survivor.init()
    template.register_helpers(app)
    app_root = survivor.app_root()
    app.jinja_loader = FileSystemLoader(os.path.join(app_root, 'templates'))
    app.static_folder = '%s/res/static' % app_root

    try: app.debug = config['flask.debug']
    except KeyError: pass

    app.run(**config['flask.settings'])
