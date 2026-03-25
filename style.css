<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>ETI Case {{ case_id }}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  <div class="page">
    <header class="hero compact">
      <div class="eyebrow">EQUINE TERRAIN INSTITUTE</div>
      <h1>Case {{ case_id }}</h1>
      <p>{{ data.horse_name }} · {{ data.discipline }}</p>
    </header>

    <div class="panel">
      <div class="grid two">
        <div>
          <p><b>Owner:</b> {{ data.owner_name }}</p>
          <p><b>Trainer:</b> {{ data.trainer_name }}</p>
          <p><b>Location:</b> {{ data.location }}</p>
        </div>
        <div>
          <p><b>Hydration:</b> {{ data.scores.hydration.score }} / {{ data.scores.hydration.band }}</p>
          <p><b>Gut:</b> {{ data.scores.gut.score }} / {{ data.scores.gut.band }}</p>
          <p><b>Muscle:</b> {{ data.scores.muscle.score }} / {{ data.scores.muscle.band }}</p>
          <p><b>Metabolic:</b> {{ data.scores.metabolic.score }} / {{ data.scores.metabolic.band }}</p>
        </div>
      </div>

      <p><b>Primary Question:</b> {{ data.primary_question }}</p>
      <p><b>Horse Story:</b> {{ data.horse_story }}</p>
      <p><a href="/reports/{{ case_id }}.txt">Download report</a></p>
    </div>
  </div>
</body>
</html>