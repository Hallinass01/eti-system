<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>ETI Cases</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  <div class="page">
    <header class="hero compact">
      <div class="eyebrow">EQUINE TERRAIN INSTITUTE</div>
      <h1>Case Queue</h1>
      <p>Standardized ETI submissions awaiting review or release.</p>
    </header>

    <div class="panel">
      <table class="table">
        <tr><th>Case ID</th><th>Horse</th><th>Discipline</th><th>Status</th><th>Primary Question</th><th>Submitted</th></tr>
        {% for c in cases %}
        <tr>
          <td><a href="/cases/{{ c.case_id }}">{{ c.case_id }}</a></td>
          <td>{{ c.horse_name }}</td>
          <td>{{ c.discipline }}</td>
          <td>{{ c.status }}</td>
          <td>{{ c.primary_question }}</td>
          <td>{{ c.submitted_at }}</td>
        </tr>
        {% endfor %}
      </table>
    </div>
  </div>
</body>
</html>