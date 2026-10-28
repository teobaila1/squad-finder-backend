from fastapi import FastAPI, APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Annotated
from datetime import datetime, timezone, timedelta
import os, bcrypt, logging, uuid
from jose import JWTError, jwt
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')


SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_SERVICE_KEY = os.environ['SUPABASE_SERVICE_KEY']  # service_role key - NICIODATA in frontend!
JWT_SECRET = os.environ.get('JWT_SECRET', 'turf-secret-key-change-in-prod')
JWT_ALGORITHM = 'HS256'
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 zile

sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

app = FastAPI()
api_router = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ---- Helpers ----

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({'sub': user_id, 'exp': expire}, JWT_SECRET, algorithm=JWT_ALGORITHM)


def db_error(action: str, exc: Exception):
    logger.error(f"DB error during {action}: {exc}")
    raise HTTPException(status_code=500, detail=f"Database error: {action}")


async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get('sub')
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    res = sb.table('users').select('*').eq('id', user_id).execute()
    if not res.data:
        raise HTTPException(status_code=401, detail="User not found")
    return res.data[0]


CurrentUser = Annotated[dict, Depends(get_current_user)]


def strip_password(user: dict) -> dict:
    user = dict(user)
    user.pop('hashed_password', None)
    return user


# ---- Pydantic Models ----

class UserSignup(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    city: str = "București"
    position: str = "midfielder"
    level: str = "intermediate"


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UpdateProfile(BaseModel):
    full_name: Optional[str] = None
    city: Optional[str] = None
    position: Optional[str] = None
    level: Optional[str] = None
    avatar_url: Optional[str] = None


class MatchCreate(BaseModel):
    title: str
    location_name: str
    location_lat: float
    location_lng: float
    scheduled_at: datetime
    players_needed: int
    format: str
    level: str
    cost_per_player: float = 0
    description: str = ""


class AvailabilitySet(BaseModel):
    location_lat: float
    location_lng: float
    radius_km: int = 5
    duration_hours: int = 2


class GoalUpdate(BaseModel):
    match_id: str
    goals: int
    assists: int


class PlayerRatingCreate(BaseModel):
    rated_id: str
    match_id: str
    fair_play: int
    punctuality: int
    skill: int


class VenueCreate(BaseModel):
    name: str
    address: str
    city: str = "București"
    location_lat: float = 44.4268
    location_lng: float = 26.1025
    surface_type: str = "artificial"
    price_per_hour: float = 0
    contact: str = ""
    working_hours: str = "08:00 - 22:00"
    description: str = ""
    photos: list = []


class VenueReviewCreate(BaseModel):
    venue_id: str
    quality: int
    surface: int
    facilities: int
    comment: str = ""


class PlayerReportCreate(BaseModel):
    reported_user_id: str
    reason: str
    comment: str = ""
    match_id: Optional[str] = None


class MessageCreate(BaseModel):
    text: str


# ---- Auth Routes ----

@api_router.post("/auth/signup")
async def signup(data: UserSignup):
    existing = sb.table('users').select('id').eq('email', data.email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Password too short")

    user_doc = {
        'email': data.email,
        'hashed_password': hash_password(data.password),
        'full_name': data.full_name,
        'city': data.city,
        'position': data.position,
        'level': data.level,
    }
    try:
        res = sb.table('users').insert(user_doc).execute()
    except Exception as exc:
        db_error("signup", exc)
    user = res.data[0]
    token = create_token(user['id'])
    return {'token': token, 'user': strip_password(user)}


@api_router.post("/auth/login")
async def login(data: UserLogin):
    res = sb.table('users').select('*').eq('email', data.email).execute()
    if not res.data or not verify_password(data.password, res.data[0]['hashed_password']):
        raise HTTPException(status_code=401, detail="Email sau parolă incorectă")
    user = res.data[0]
    token = create_token(user['id'])
    return {'token': token, 'user': strip_password(user)}


@api_router.get("/auth/me")
async def me(current_user: CurrentUser):
    return strip_password(current_user)


@api_router.put("/auth/profile")
async def update_profile(data: UpdateProfile, current_user: CurrentUser):
    update = {k: v for k, v in data.dict().items() if v is not None}
    if update:
        sb.table('users').update(update).eq('id', current_user['id']).execute()
    res = sb.table('users').select('*').eq('id', current_user['id']).execute()
    return strip_password(res.data[0])


# ---- Matches Routes ----

def total_spots(fmt: str) -> int:
    try:
        per_side = int(fmt.split('v')[0])
        return per_side * 2
    except Exception:
        return 10



@api_router.get("/matches/{match_id}/messages")
async def get_match_messages(match_id: str, current_user: CurrentUser):
    # Aducem mesajele ordonate cronologic (cele mai vechi primele)
    res = sb.table('match_messages').select('*').eq('match_id', match_id).order('created_at', desc=False).execute()
    return res.data



@api_router.post("/matches/{match_id}/messages")
async def send_match_message(match_id: str, data: MessageCreate, current_user: CurrentUser):
    message_doc = {
        'match_id': match_id,
        'user_id': current_user['id'],
        'user_name': current_user.get('full_name', 'Jucător'),
        'text': data.text
    }
    res = sb.table('match_messages').insert(message_doc).execute()
    return res.data[0]




@api_router.delete("/matches/{match_id}")
async def delete_match(match_id: str, current_user: CurrentUser):
    # 1. Verificăm dacă meciul există
    res = sb.table('matches').select('*').eq('id', match_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Meciul nu a fost găsit.")
    
    match = res.data[0]

    # 2. Verificăm dacă utilizatorul care face cererea este organizatorul
    if match['organizer_id'] != current_user['id']:
        raise HTTPException(status_code=403, detail="Nu ai permisiunea de a șterge acest meci.")

    # 3. Ștergem meciul. 
    # (Datorită setărilor bazei de date 'on delete cascade', înregistrările din match_players asociate ar trebui șterse automat)
    try:
        sb.table('matches').delete().eq('id', match_id).execute()
    except Exception as exc:
        db_error("delete_match", exc)

    return {'message': 'Meciul a fost șters cu succes.'}



@api_router.post("/matches")
async def create_match(data: MatchCreate, current_user: CurrentUser):
    invite_code = str(uuid.uuid4())[:8].upper()
    match_doc = {
        'organizer_id': current_user['id'],
        'organizer_name': current_user.get('full_name', ''),
        'title': data.title,
        'location_name': data.location_name,
        'location_lat': data.location_lat,
        'location_lng': data.location_lng,
        'scheduled_at': data.scheduled_at.isoformat(),
        'players_needed': data.players_needed,
        'current_players': 1,
        'format': data.format,
        'level': data.level,
        'cost_per_player': data.cost_per_player,
        'description': data.description,
        'status': 'open',
        'invite_code': invite_code,
    }
    res = sb.table('matches').insert(match_doc).execute()
    match = res.data[0]

    sb.table('match_players').insert({
        'match_id': match['id'],
        'user_id': current_user['id'],
        'user_name': current_user.get('full_name', ''),
        'position': current_user.get('position', ''),
        'status': 'confirmed',
    }).execute()

    return match


@api_router.get("/matches")
async def get_matches(
    level: Optional[str] = None,
    format: Optional[str] = None,
    match_status: Optional[str] = 'open'
):
    query = sb.table('matches').select('*')
    if level:
        query = query.eq('level', level)
    if format:
        query = query.eq('format', format)
    if match_status:
        query = query.eq('status', match_status)
    res = query.order('scheduled_at', desc=False).limit(100).execute()
    return res.data


@api_router.get("/matches/{match_id}")
async def get_match(match_id: str):
    res = sb.table('matches').select('*').eq('id', match_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Match not found")
    return res.data[0]


@api_router.get("/matches/{match_id}/players")
async def get_match_players(match_id: str):
    res = sb.table('match_players').select('*').eq('match_id', match_id).eq('status', 'confirmed').execute()
    return res.data


@api_router.post("/matches/{match_id}/join")
async def join_match(match_id: str, current_user: CurrentUser):
    match_res = sb.table('matches').select('*').eq('id', match_id).execute()
    if not match_res.data:
        raise HTTPException(status_code=404, detail="Match not found")
    match = match_res.data[0]

    existing = sb.table('match_players').select('id').eq('match_id', match_id) \
        .eq('user_id', current_user['id']).neq('status', 'cancelled').execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Already in this match")

    spots = total_spots(match.get('format', '5v5'))
    current = match['current_players']
    player_status = 'confirmed' if current < spots else 'waitlist'

    sb.table('match_players').insert({
        'match_id': match_id,
        'user_id': current_user['id'],
        'user_name': current_user.get('full_name', ''),
        'position': current_user.get('position', ''),
        'status': player_status,
    }).execute()

    if player_status == 'confirmed':
        new_count = current + 1
        new_status = 'full' if new_count >= spots else 'open'
        sb.table('matches').update({'current_players': new_count, 'status': new_status}).eq('id', match_id).execute()

        if match['organizer_id'] != current_user['id']:
            sb.table('notifications').insert({
                'user_id': match['organizer_id'],
                'type': 'player_joined',
                'title': 'Jucător nou s-a alăturat!',
                'message': f"{current_user.get('full_name', 'Un jucător')} a confirmat pentru meciul tău",
                'is_read': False,
                'data': {'match_id': match_id},
            }).execute()

        if new_status == 'full':
            confirmed = sb.table('match_players').select('user_id').eq('match_id', match_id) \
                .eq('status', 'confirmed').execute()
            for p in confirmed.data:
                sb.table('notifications').insert({
                    'user_id': p['user_id'],
                    'type': 'match_full',
                    'title': '⚽ Meciul e complet!',
                    'message': f"Meciul din {match.get('location_name', '')} e gata. Toți jucătorii sunt confirmați!",
                    'is_read': False,
                    'data': {'match_id': match_id},
                }).execute()

    return {'status': player_status}


@api_router.delete("/matches/{match_id}/leave")
async def leave_match(match_id: str, current_user: CurrentUser):
    player = sb.table('match_players').select('*').eq('match_id', match_id) \
        .eq('user_id', current_user['id']).eq('status', 'confirmed').execute()
    if not player.data:
        raise HTTPException(status_code=404, detail="Not in this match")

    sb.table('match_players').update({'status': 'cancelled'}).eq('match_id', match_id) \
        .eq('user_id', current_user['id']).execute()

    match_res = sb.table('matches').select('*').eq('id', match_id).execute()
    if match_res.data:
        match = match_res.data[0]
        new_count = max(0, match['current_players'] - 1)
        spots = total_spots(match.get('format', '5v5'))
        new_status = 'open' if new_count < spots else 'full'
        sb.table('matches').update({'current_players': new_count, 'status': new_status}).eq('id', match_id).execute()

        waitlisted = sb.table('match_players').select('id').eq('match_id', match_id) \
            .eq('status', 'waitlist').limit(1).execute()
        if waitlisted.data:
            sb.table('match_players').update({'status': 'confirmed'}).eq('id', waitlisted.data[0]['id']).execute()

    return {'message': 'Left match'}


@api_router.get("/matches/invite/{invite_code}")
async def get_match_by_invite(invite_code: str):
    res = sb.table('matches').select('*').eq('invite_code', invite_code.upper()).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Match not found")
    return res.data[0]


@api_router.get("/my-matches")
async def get_my_matches(current_user: CurrentUser):
    entries = sb.table('match_players').select('match_id').eq('user_id', current_user['id']) \
        .eq('status', 'confirmed').execute()
    match_ids = [e['match_id'] for e in entries.data]
    if not match_ids:
        return []
    res = sb.table('matches').select('*').in_('id', match_ids) \
        .order('scheduled_at', desc=True).execute()
    return res.data


# ---- Availability Routes ----

@api_router.post("/availability")
async def set_availability(data: AvailabilitySet, current_user: CurrentUser):
    sb.table('availability').update({'is_active': False}).eq('user_id', current_user['id']).execute()

    avail_doc = {
        'user_id': current_user['id'],
        'user_name': current_user.get('full_name', ''),
        'position': current_user.get('position', ''),
        'level': current_user.get('level', ''),
        'location_lat': data.location_lat,
        'location_lng': data.location_lng,
        'radius_km': data.radius_km,
        'available_until': (datetime.now(timezone.utc) + timedelta(hours=data.duration_hours)).isoformat(),
        'is_active': True,
    }
    res = sb.table('availability').insert(avail_doc).execute()
    return res.data[0]


@api_router.delete("/availability")
async def deactivate_availability(current_user: CurrentUser):
    sb.table('availability').update({'is_active': False}).eq('user_id', current_user['id']).execute()
    return {'message': 'Deactivated'}


@api_router.get("/availability/active")
async def get_my_active_availability(current_user: CurrentUser):
    res = sb.table('availability').select('*').eq('user_id', current_user['id']) \
        .eq('is_active', True).limit(1).execute()
    if not res.data:
        return None
    avail = res.data[0]
    if datetime.fromisoformat(avail['available_until']) < datetime.now(timezone.utc):
        sb.table('availability').update({'is_active': False}).eq('id', avail['id']).execute()
        return None
    return avail


@api_router.get("/availability/nearby")
async def get_nearby_available(lat: float, lng: float, radius_km: float = 10, current_user: CurrentUser = None):
    now = datetime.now(timezone.utc).isoformat()
    active = sb.table('availability').select('*').eq('is_active', True).gt('available_until', now).execute()

    result = []
    for avail in active.data:
        if current_user and avail['user_id'] == current_user['id']:
            continue
        dlat = abs(avail['location_lat'] - lat)
        dlng = abs(avail['location_lng'] - lng)
        dist_approx = (dlat ** 2 + dlng ** 2) ** 0.5 * 111
        if dist_approx <= radius_km:
            result.append(avail)

    return result


# ---- Stats Routes ----

@api_router.post("/stats")
async def update_stats(data: GoalUpdate, current_user: CurrentUser):
    existing = sb.table('player_stats').select('id').eq('match_id', data.match_id) \
        .eq('user_id', current_user['id']).execute()
    if existing.data:
        sb.table('player_stats').update({'goals': data.goals, 'assists': data.assists}) \
            .eq('id', existing.data[0]['id']).execute()
    else:
        sb.table('player_stats').insert({
            'user_id': current_user['id'],
            'match_id': data.match_id,
            'goals': data.goals,
            'assists': data.assists,
        }).execute()
    return {'message': 'Stats updated'}


@api_router.get("/stats/me")
async def get_my_stats(current_user: CurrentUser):
    stats = sb.table('player_stats').select('goals,assists').eq('user_id', current_user['id']).execute()
    goals = sum(s['goals'] for s in stats.data)
    assists = sum(s['assists'] for s in stats.data)
    played_res = sb.table('match_players').select('id', count='exact') \
        .eq('user_id', current_user['id']).eq('status', 'confirmed').execute()
    played = played_res.count or 0

    ratings = sb.table('player_ratings').select('fair_play,punctuality,skill') \
        .eq('rated_id', current_user['id']).execute()
    avg_rating = 0.0
    if ratings.data:
        total = sum((r['fair_play'] + r['punctuality'] + r['skill']) / 3 for r in ratings.data)
        avg_rating = round(total / len(ratings.data), 1)

    return {
        'matches_played': played,
        'goals': goals,
        'assists': assists,
        'avg_rating': avg_rating,
        'ratings_count': len(ratings.data)
    }


# ---- Ratings Routes ----

@api_router.post("/ratings")
async def rate_player(data: PlayerRatingCreate, current_user: CurrentUser):
    if data.rated_id == current_user['id']:
        raise HTTPException(status_code=400, detail="Cannot rate yourself")
    existing = sb.table('player_ratings').select('id').eq('rater_id', current_user['id']) \
        .eq('rated_id', data.rated_id).eq('match_id', data.match_id).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Already rated")

    sb.table('player_ratings').insert({
        'rater_id': current_user['id'],
        'rater_name': current_user.get('full_name', ''),
        'rated_id': data.rated_id,
        'match_id': data.match_id,
        'fair_play': data.fair_play,
        'punctuality': data.punctuality,
        'skill': data.skill,
    }).execute()

    sb.table('notifications').insert({
        'user_id': data.rated_id,
        'type': 'new_rating',
        'title': '⭐ Rating nou primit',
        'message': f"{current_user.get('full_name', 'Un jucător')} ți-a acordat un rating",
        'is_read': False,
        'data': {'match_id': data.match_id},
    }).execute()

    return {'message': 'Rating saved'}


# ---- Notifications Routes ----

@api_router.get("/notifications")
async def get_notifications(current_user: CurrentUser):
    res = sb.table('notifications').select('*').eq('user_id', current_user['id']) \
        .order('created_at', desc=True).limit(50).execute()
    return res.data


@api_router.get("/notifications/unread-count")
async def get_unread_count(current_user: CurrentUser):
    res = sb.table('notifications').select('id', count='exact') \
        .eq('user_id', current_user['id']).eq('is_read', False).execute()
    return {'count': res.count or 0}


@api_router.put("/notifications/read-all")
async def mark_all_read(current_user: CurrentUser):
    sb.table('notifications').update({'is_read': True}).eq('user_id', current_user['id']).execute()
    return {'message': 'All read'}


@api_router.put("/notifications/{notif_id}/read")
async def mark_notification_read(notif_id: str, current_user: CurrentUser):
    try:
        sb.table('notifications').update({'is_read': True}).eq('id', notif_id) \
            .eq('user_id', current_user['id']).execute()
    except Exception:
        pass
    return {'message': 'Read'}


# ---- Profile Route ----

@api_router.get("/profile/{user_id}")
async def get_profile(user_id: str):
    user_res = sb.table('users').select('*').eq('id', user_id).execute()
    if not user_res.data:
        raise HTTPException(status_code=404, detail="User not found")
    user = strip_password(user_res.data[0])

    stats = sb.table('player_stats').select('goals,assists').eq('user_id', user_id).execute()
    goals = sum(s['goals'] for s in stats.data)
    assists = sum(s['assists'] for s in stats.data)
    played_res = sb.table('match_players').select('id', count='exact') \
        .eq('user_id', user_id).eq('status', 'confirmed').execute()
    played = played_res.count or 0

    ratings = sb.table('player_ratings').select('fair_play,punctuality,skill').eq('rated_id', user_id).execute()
    avg_rating = 0.0
    if ratings.data:
        total = sum((r['fair_play'] + r['punctuality'] + r['skill']) / 3 for r in ratings.data)
        avg_rating = round(total / len(ratings.data), 1)

    entries = sb.table('match_players').select('match_id').eq('user_id', user_id) \
        .eq('status', 'confirmed').order('joined_at', desc=True).limit(20).execute()
    match_history = []
    for entry in entries.data:
        m = sb.table('matches').select('*').eq('id', entry['match_id']).execute()
        if m.data:
            match_history.append(m.data[0])

    return {
        **user,
        'stats': {
            'matches_played': played,
            'goals': goals,
            'assists': assists,
            'avg_rating': avg_rating,
        },
        'match_history': match_history[:10]
    }


# ---- Venues Routes ----

@api_router.get("/venues")
async def get_venues(
    city: Optional[str] = None,
    surface_type: Optional[str] = None,
    search: Optional[str] = None
):
    query = sb.table('venues').select('*')
    if city:
        query = query.eq('city', city)
    if surface_type:
        query = query.eq('surface_type', surface_type)
    if search:
        query = query.or_(f"name.ilike.%{search}%,address.ilike.%{search}%")
    res = query.order('name').limit(200).execute()

    result = []
    for v in res.data:
        reviews = sb.table('venue_reviews').select('quality,surface,facilities').eq('venue_id', v['id']).execute()
        v['review_count'] = len(reviews.data)
        if reviews.data:
            v['avg_rating'] = round(
                sum((r['quality'] + r['surface'] + r['facilities']) / 3 for r in reviews.data) / len(reviews.data), 1
            )
        else:
            v['avg_rating'] = 0.0
        match_count = sb.table('matches').select('id', count='exact') \
            .ilike('location_name', f"%{v['name']}%").execute()
        v['match_count'] = match_count.count or 0
        result.append(v)
    return result


@api_router.get("/venues/{venue_id}")
async def get_venue(venue_id: str):
    res = sb.table('venues').select('*').eq('id', venue_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Venue not found")
    venue = res.data[0]

    reviews_res = sb.table('venue_reviews').select('*').eq('venue_id', venue_id) \
        .order('created_at', desc=True).limit(50).execute()
    reviews = reviews_res.data

    venue['reviews'] = reviews
    venue['review_count'] = len(reviews)
    if reviews:
        venue['avg_quality'] = round(sum(r['quality'] for r in reviews) / len(reviews), 1)
        venue['avg_surface'] = round(sum(r['surface'] for r in reviews) / len(reviews), 1)
        venue['avg_facilities'] = round(sum(r['facilities'] for r in reviews) / len(reviews), 1)
        venue['avg_rating'] = round(
            (venue['avg_quality'] + venue['avg_surface'] + venue['avg_facilities']) / 3, 1
        )
    else:
        venue['avg_quality'] = venue['avg_surface'] = venue['avg_facilities'] = venue['avg_rating'] = 0.0

    match_count = sb.table('matches').select('id', count='exact') \
        .ilike('location_name', f"%{venue['name']}%").execute()
    venue['match_count'] = match_count.count or 0
    return venue


@api_router.post("/venues")
async def create_venue(data: VenueCreate, current_user: CurrentUser):
    existing = sb.table('venues').select('id').eq('name', data.name).eq('city', data.city).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Venue already exists in this city")

    venue_doc = {
        'name': data.name,
        'address': data.address,
        'city': data.city,
        'location_lat': data.location_lat,
        'location_lng': data.location_lng,
        'surface_type': data.surface_type,
        'price_per_hour': data.price_per_hour,
        'contact': data.contact,
        'working_hours': data.working_hours,
        'description': data.description,
        'photos': data.photos,
        'added_by': current_user['id'],
        'verified': False,
    }
    res = sb.table('venues').insert(venue_doc).execute()
    return res.data[0]


@api_router.post("/venues/{venue_id}/reviews")
async def add_venue_review(venue_id: str, data: VenueReviewCreate, current_user: CurrentUser):
    venue = sb.table('venues').select('id').eq('id', venue_id).execute()
    if not venue.data:
        raise HTTPException(status_code=404, detail="Venue not found")

    existing = sb.table('venue_reviews').select('id').eq('venue_id', venue_id) \
        .eq('user_id', current_user['id']).execute()
    if existing.data:
        sb.table('venue_reviews').update({
            'quality': data.quality, 'surface': data.surface,
            'facilities': data.facilities, 'comment': data.comment
        }).eq('id', existing.data[0]['id']).execute()
        return {'message': 'Review updated'}

    sb.table('venue_reviews').insert({
        'venue_id': venue_id,
        'user_id': current_user['id'],
        'user_name': current_user.get('full_name', ''),
        'quality': data.quality,
        'surface': data.surface,
        'facilities': data.facilities,
        'comment': data.comment,
    }).execute()
    return {'message': 'Review added'}


# ---- Reports Route ----

@api_router.post("/reports")
async def report_player(data: PlayerReportCreate, current_user: CurrentUser):
    if data.reported_user_id == current_user['id']:
        raise HTTPException(status_code=400, detail="Nu te poți raporta pe tine însuți")

    if data.match_id:
        existing = sb.table('reports').select('id').eq('reporter_id', current_user['id']) \
            .eq('reported_user_id', data.reported_user_id).eq('match_id', data.match_id).execute()
        if existing.data:
            raise HTTPException(status_code=400, detail="Ai raportat deja acest jucător pentru meciul respectiv")

    sb.table('reports').insert({
        'reporter_id': current_user['id'],
        'reporter_name': current_user.get('full_name', ''),
        'reported_user_id': data.reported_user_id,
        'reason': data.reason,
        'comment': data.comment,
        'match_id': data.match_id,
        'status': 'pending',
    }).execute()
    return {'message': 'Raport trimis cu succes'}


# ---- Include Router ----
app.include_router(api_router)
