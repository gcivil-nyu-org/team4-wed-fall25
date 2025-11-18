# Deployment Notes - WebSocket Support on AWS Elastic Beanstalk

## Changes Made for Production Deployment

### 1. Updated Procfile
- Changed from Gunicorn (WSGI) to Daphne (ASGI) to support WebSocket connections
- **Before**: `web: gunicorn note2web.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120`
- **After**: `web: daphne -b 0.0.0.0 -p 8000 note2web.asgi:application`

### 2. Channel Layers Configuration
- **Development**: Uses `InMemoryChannelLayer` (single instance only)
- **Production**: Uses Redis via `channels_redis` (required for multiple instances/workers)

### 3. Redis Setup Required

For production deployment, you **MUST** set up Redis for channel layers. Options:

#### Option A: AWS ElastiCache (Recommended)
1. Create an ElastiCache Redis cluster in the same VPC as your EB environment
2. Set environment variables in EB:
   - `REDIS_HOST`: Your ElastiCache endpoint
   - `REDIS_PORT`: 6379 (default)

#### Option B: Environment Variables
Set these in Elastic Beanstalk environment configuration:
- `REDIS_HOST`: Redis server hostname
- `REDIS_PORT`: Redis server port (default: 6379)
- Or `REDIS_URL`: Full Redis URL (e.g., `redis://host:port`)

### 4. WebSocket Configuration
- Added `.ebextensions/05_websocket.config` to increase ALB idle timeout for WebSocket connections
- ALB (Application Load Balancer) supports WebSocket connections by default
- Increased timeout to 3600 seconds to support long-lived WebSocket connections

## Deployment Steps

1. **Set up Redis** (if not already done):
   - Create ElastiCache Redis cluster
   - Note the endpoint and port

2. **Configure Environment Variables** in Elastic Beanstalk:
   - Go to Configuration → Software → Environment properties
   - Add:
     - `REDIS_HOST`: Your Redis endpoint
     - `REDIS_PORT`: 6379

3. **Deploy**:
   - The updated Procfile will automatically use Daphne
   - WebSocket support will be enabled via nginx configuration

## Important Notes

⚠️ **Without Redis**: 
- WebSocket will work on single-instance deployments
- Real-time comments will NOT work across multiple instances
- Each instance will have its own isolated channel layer

✅ **With Redis**:
- WebSocket works across all instances
- Real-time comments work for all users regardless of which instance they're connected to
- Production-ready setup

## Testing After Deployment

1. Navigate to a test model page
2. Open browser DevTools (F12) → Console
3. Check for WebSocket connection: Should see connection to `wss://your-domain.com/ws/model/<id>/comments/`
4. Test real-time comments:
   - Open page in two different browser tabs
   - Add comment in one tab
   - Should appear in real-time in the other tab

## Troubleshooting

### WebSocket Connection Fails
- Verify Daphne is running (check EB logs: `eb logs`)
- Check security groups allow WebSocket connections (port 80/443)
- Verify ALB is configured (not Classic Load Balancer)
- Check browser console for WebSocket connection errors

### Comments Not Real-Time Across Instances
- Verify Redis is configured and accessible
- Check `REDIS_HOST` and `REDIS_PORT` environment variables
- Check ElastiCache security groups allow connections from EB instances

### Daphne Not Starting
- Check EB logs for errors
- Verify `daphne` is in requirements.txt
- Check Procfile syntax

