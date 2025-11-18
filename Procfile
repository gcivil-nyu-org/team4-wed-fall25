# Daphne supports both HTTP and WebSocket connections
# To revert to Gunicorn (no WebSocket support), replace this line with:
# web: gunicorn note2web.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120
web: daphne -b 0.0.0.0 -p 8000 note2web.asgi:application
