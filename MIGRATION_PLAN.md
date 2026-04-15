# NegoRide Canada — Laravel → Python Backend Migration Plan

> **Goal**: Migrate the entire Laravel PHP backend to a Python (Flask) backend while maintaining **100% API response compatibility** with the existing Flutter mobile app and admin dashboard.  
> **Benchmark Project**: `/Users/mac/Desktop/py-voip/` (Flask + React)  
> **Current Backend**: `/Applications/MAMP/htdocs/negoride-canada-api/` (Laravel + Encore Admin)  
> **New Backend**: `/Applications/MAMP/htdocs/negoride-canada-api/negoride-canada-py-api/`  
> **Database**: MySQL (`negoride`) — **reuse existing database, no schema changes**

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Project Structure](#2-project-structure)
3. [Task Breakdown](#3-task-breakdown)
   - Phase 1: Project Scaffolding & Configuration
   - Phase 2: Database Models (SQLAlchemy)
   - Phase 3: Authentication & Middleware
   - Phase 4: Mobile API Endpoints
   - Phase 5: Admin Dashboard (API + UI)
   - Phase 6: Stripe Payment Integration
   - Phase 7: File Uploads & Storage
   - Phase 8: Push Notifications (OneSignal)
   - Phase 9: Testing & Validation
   - Phase 10: Deployment & Cutover
4. [Response Format Contract](#4-response-format-contract)
5. [Endpoint Mapping (Laravel → Python)](#5-endpoint-mapping)
6. [Database Schema Reference](#6-database-schema-reference)
7. [Risk Register](#7-risk-register)

---

## 1. Architecture Overview

### Current Stack (Laravel)
```
Flutter App ── HTTPS ──> Laravel PHP (MAMP) ──> MySQL (negoride)
                              │
                     Encore Admin Panel (Blade templates)
                              │
                     Stripe API, OneSignal API
```

### New Stack (Python)
```
Flutter App ── HTTPS ──> Flask Python ──> MySQL (negoride) [SAME DB]
                              │
                     React Admin Panel (from benchmark)
                              │
                     Stripe API, OneSignal API
```

### Key Principles
- **Zero changes to the Flutter app** — all API responses must be byte-identical in structure
- **Same MySQL database** — connect to existing `negoride` DB, no migrations needed
- **Same response format**: `{ "code": 1, "message": "...", "data": {...} }`
- **Same JWT authentication** — token format must be compatible
- **Same file storage paths** — uploaded files must be accessible at same URLs
- **Same Stripe webhook handling** — payment flow must not break

---

## 2. Project Structure

```
negoride-canada-py-api/
├── backend/
│   ├── app.py                          # Flask app factory (from benchmark)
│   ├── config.py                       # Environment-based config (from benchmark)
│   ├── migrate.py                      # Laravel-style migration CLI (from benchmark)
│   ├── requirements.txt                # Python dependencies
│   ├── .env                            # Environment variables
│   ├── .env.example                    # Template
│   │
│   ├── models/                         # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── user.py                     # AdminUser (admin_users table)
│   │   ├── trip.py                     # Trip
│   │   ├── trip_booking.py             # TripBooking
│   │   ├── negotiation.py              # Negotiation
│   │   ├── negotiation_record.py       # NegotiationRecord
│   │   ├── scheduled_booking.py        # ScheduledBooking
│   │   ├── payment.py                  # Payment
│   │   ├── transaction.py              # Transaction
│   │   ├── user_wallet.py              # UserWallet
│   │   ├── payout_account.py           # PayoutAccount
│   │   ├── payout_request.py           # PayoutRequest
│   │   ├── chat_head.py                # ChatHead
│   │   ├── chat_message.py             # ChatMessage
│   │   ├── trip_note.py                # TripNote
│   │   ├── company.py                  # Company
│   │   ├── event.py                    # Event
│   │   ├── task.py                     # Task
│   │   ├── patient.py                  # Patient
│   │   ├── patient_record.py           # PatientRecord
│   │   ├── treatment_record.py         # TreatmentRecord
│   │   ├── project.py                  # Project
│   │   └── route_stage.py              # RouteStage
│   │
│   ├── routes/                         # Blueprint-organized API routes
│   │   ├── __init__.py
│   │   ├── auth.py                     # /api/users/* (login, register, OTP)
│   │   ├── profile.py                  # /api/profile/* (update, avatar, delete)
│   │   ├── trips.py                    # /api/trips* (CRUD, bookings)
│   │   ├── negotiations.py             # /api/negotiations* (CRUD, records, payment)
│   │   ├── bookings.py                 # /api/bookings* (scheduled bookings)
│   │   ├── wallet.py                   # /api/wallet* (balance, transactions)
│   │   ├── payout_account.py           # /api/payout-account* (Stripe Connect)
│   │   ├── payout_requests.py          # /api/payout-requests* (withdrawals)
│   │   ├── chat.py                     # /api/chat* (messages, heads)
│   │   ├── location.py                 # /api/update-location, go-on-off
│   │   ├── resources.py                # /api/* (drivers, SACCOs, services)
│   │   ├── webhooks.py                 # /api/stripe-webhook
│   │   └── admin.py                    # /api/admin/* (dashboard, CRUD)
│   │
│   ├── services/                       # Business logic services
│   │   ├── __init__.py
│   │   ├── stripe_service.py           # Stripe payment links, webhooks, Connect
│   │   ├── notification_service.py     # OneSignal push notifications
│   │   ├── wallet_service.py           # Wallet balance operations
│   │   └── trip_service.py             # Trip search, matching
│   │
│   ├── utils/                          # Utility modules
│   │   ├── __init__.py
│   │   ├── auth.py                     # JWT decorators (from benchmark)
│   │   ├── response.py                 # Standard response builder
│   │   └── helpers.py                  # Date formatting, greetings, etc.
│   │
│   └── uploads/                        # User file storage
│       ├── profiles/                   # Profile avatars
│       └── documents/                  # Driver documents
│
├── frontend/                           # React Admin Dashboard (from benchmark)
│   ├── package.json
│   ├── public/
│   └── src/
│       ├── App.js                      # Route config
│       ├── components/
│       │   ├── AdminPanel.js           # Main admin (from benchmark)
│       │   ├── Dashboard.js            # Stats overview
│       │   ├── UserManagement.js       # Driver/Customer CRUD
│       │   ├── TripManagement.js       # Trip CRUD
│       │   ├── NegotiationManagement.js # Negotiation views
│       │   ├── BookingManagement.js    # Booking views
│       │   ├── PaymentManagement.js    # Payment views
│       │   └── Navbar.js
│       ├── contexts/
│       │   ├── AuthContext.js          # From benchmark
│       │   └── DashboardContext.js     # From benchmark
│       └── services/
│           └── api.js                  # Axios + JWT interceptors (from benchmark)
│
├── MIGRATION_PLAN.md                   # This file
└── README.md                           # Setup instructions
```

---

## 3. Task Breakdown

---

### PHASE 1: Project Scaffolding & Configuration

#### Task 1.1: Initialize Flask Project
**Status**: `[ ]`  
**Description**: Set up the Flask application with the same factory pattern used in the benchmark project.

**Steps**:
1. Copy `app.py` from benchmark (`/Users/mac/Desktop/py-voip/backend/app.py`)
2. Copy `config.py` from benchmark (`/Users/mac/Desktop/py-voip/backend/config.py`)
3. Modify `config.py` to use `negoride` database instead of `py_voip`
4. Update `SQLALCHEMY_DATABASE_URI` to point to existing MySQL database
5. Configure JWT secret key to match Laravel's JWT secret (or generate new one — see Task 3.1)

**Config changes from benchmark**:
```python
# config.py
class Config:
    DB_NAME = os.getenv('DB_DATABASE', 'negoride')  # Changed from py_voip
    # Keep MAMP socket: /Applications/MAMP/tmp/mysql/mysql.sock
    # Keep PyMySQL as driver
```

**Files to create**:
- `backend/app.py`
- `backend/config.py`
- `backend/.env`
- `backend/.env.example`

---

#### Task 1.2: Create Requirements File
**Status**: `[ ]`  
**Description**: Define all Python dependencies.

**Steps**:
1. Start from benchmark `requirements.txt`
2. Add NegoRide-specific packages (Stripe, etc.)

**`requirements.txt`**:
```
# Core (from benchmark)
Flask==3.0.0
Flask-SQLAlchemy==3.1.1
Flask-JWT-Extended==4.6.0
Flask-CORS==4.0.0
python-dotenv==1.0.0
bcrypt==4.1.2
PyMySQL==1.1.0
cryptography>=46.0.0

# Additional for NegoRide
stripe==8.0.0              # Stripe payment integration
requests==2.31.0           # HTTP client for OneSignal API
Werkzeug==3.0.0            # File upload handling
Pillow==10.2.0             # Image processing for avatars
gunicorn==21.2.0           # Production WSGI server
```

**Files to create**:
- `backend/requirements.txt`

---

#### Task 1.3: Environment Configuration
**Status**: `[ ]`  
**Description**: Set up environment variables matching the Laravel `.env`.

**`.env.example`**:
```bash
# Flask
SECRET_KEY=your-secret-key
FLASK_ENV=development
FLASK_DEBUG=true

# Database (reuse Laravel's MySQL)
DB_CONNECTION=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE=negoride
DB_USERNAME=root
DB_PASSWORD=root
DB_SOCKET=/Applications/MAMP/tmp/mysql/mysql.sock

# JWT
JWT_SECRET_KEY=your-jwt-secret
JWT_ACCESS_TOKEN_EXPIRES=315360000

# Stripe
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
SERVICE_FEE_PERCENTAGE=10

# OneSignal
ONESIGNAL_APP_ID=56ef70cd-45a3-4a66-9838-3146fbbffe77
ONESIGNAL_REST_API_KEY=your-onesignal-key

# File Storage
UPLOAD_FOLDER=uploads
MAX_CONTENT_LENGTH=16777216

# App
APP_URL=https://negoride.ugnews24.info
APP_NAME=NegoRide Canada
```

**Files to create**:
- `backend/.env`
- `backend/.env.example`

---

#### Task 1.4: Set Up Migration CLI
**Status**: `[ ]`  
**Description**: Copy the Laravel-style migration CLI from the benchmark project. Since we're reusing the existing database, we won't run new migrations — but we need the tool for future schema changes.

**Steps**:
1. Copy `migrate.py` from benchmark
2. Copy `database/migrations/` directory structure
3. No need to run migrations — the `negoride` DB is already set up

**Files to create**:
- `backend/migrate.py`
- `backend/database/migrations/` (empty, for future use)

---

### PHASE 2: Database Models (SQLAlchemy)

#### Task 2.1: Create User Model (admin_users table)
**Status**: `[ ]`  
**Description**: Map the `admin_users` table to a SQLAlchemy model. This is the most critical model — it stores all users (admins, drivers, customers).

**Steps**:
1. Create `backend/models/user.py`
2. Map ALL columns from the `admin_users` table (see Schema Reference §6.1)
3. Include `to_dict()` method that matches Laravel's JSON serialization
4. Include `set_password()` and `check_password()` using bcrypt
5. Include relationships to wallets, trips, negotiations, etc.

**Critical columns to map**:
```python
class AdminUser(db.Model):
    __tablename__ = 'admin_users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(190), unique=True)
    name = db.Column(db.String(255))
    first_name = db.Column(db.String(255), nullable=True)
    last_name = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(255), nullable=True)
    phone_number_2 = db.Column(db.String(255), nullable=True)
    password = db.Column(db.String(60))  # bcrypt hash
    avatar = db.Column(db.String(255), nullable=True)
    remember_token = db.Column(db.String(100), nullable=True)
    
    # Country info
    country_name = db.Column(db.String(50), default='Canada')
    country_code = db.Column(db.String(5), default='+1')
    country_short_name = db.Column(db.String(3), default='CA')
    
    # Personal info
    date_of_birth = db.Column(db.Date, nullable=True)
    place_of_birth = db.Column(db.String(255), nullable=True)
    sex = db.Column(db.Enum('Male', 'Female'), nullable=True)
    home_address = db.Column(db.Text, nullable=True)
    current_address = db.Column(db.Text, nullable=True)
    
    # Role & status
    user_type = db.Column(db.Enum('Admin', 'Driver', 'Pending Driver', 'Customer'), default='Customer')
    status = db.Column(db.Enum('0', '1', '2'), default='1')
    ready_for_trip = db.Column(db.Enum('Yes', 'No'), default='No')
    
    # Driver info
    enterprise_id = db.Column(db.String(255), nullable=True)
    nin = db.Column(db.String(255), nullable=True)
    driving_license_issue_authority = db.Column(db.String(255), nullable=True)
    driving_license_issue_date = db.Column(db.Date, nullable=True)
    driving_license_validity = db.Column(db.Date, nullable=True)
    
    # Service capabilities (Yes/No enums)
    is_car = is_boda = is_ambulance = is_delivery = ...  # Map all service fields
    is_car_approved = is_boda_approved = ...               # Map all approval fields
    
    # Location tracking
    latitude = db.Column(db.String(255), nullable=True)
    longitude = db.Column(db.String(255), nullable=True)
    
    # Soft delete
    status_field = db.Column(db.String(255), nullable=True)  # 'Deleted' for soft-deleted
    deleted_at = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
```

**⚠️ CRITICAL**: Laravel uses `bcrypt` with `$2y$` prefix. Python bcrypt uses `$2b$`. They are compatible — PHP `password_verify()` and Python `bcrypt.checkpw()` both handle `$2y$` and `$2b$`. **No password re-hashing needed.**

---

#### Task 2.2: Create Negotiation Models
**Status**: `[ ]`  
**Description**: Map `negotiations` and `negotiation_records` tables.

**Steps**:
1. Create `backend/models/negotiation.py` — see Schema §6.2
2. Create `backend/models/negotiation_record.py` — see Schema §6.3
3. Include `to_dict()` that matches Laravel's `toArray()` output
4. Prices are in CENTS (int) for `initial_price`, records price; `agreed_price` is decimal(10,2) in dollars

---

#### Task 2.3: Create Trip & Booking Models
**Status**: `[ ]`  
**Description**: Map `trips`, `trip_bookings`, `scheduled_bookings`, `trip_notes` tables.

**Steps**:
1. Create `backend/models/trip.py` — includes `slots`, driver/route info
2. Create `backend/models/trip_booking.py` — booking with Stripe fields
3. Create `backend/models/scheduled_booking.py` — see Schema §6.8 (prices in cents)
4. Create `backend/models/trip_note.py` — see Schema §6.9

---

#### Task 2.4: Create Payment & Wallet Models
**Status**: `[ ]`  
**Description**: Map `payments`, `transactions`, `user_wallets` tables.

**Steps**:
1. Create `backend/models/payment.py` — see Schema §6.4
2. Create `backend/models/transaction.py` — see Schema §6.5
3. Create `backend/models/user_wallet.py` — see Schema §6.6
4. Include relationship to users, negotiations, bookings

---

#### Task 2.5: Create Payout Models
**Status**: `[ ]`  
**Description**: Map `payout_accounts` and `payout_requests` tables.

**Steps**:
1. Create `backend/models/payout_account.py` — see Schema §6.7 (Stripe Connect fields)
2. Create `backend/models/payout_request.py` — see Schema §6.8

---

#### Task 2.6: Create Chat Models
**Status**: `[ ]`  
**Description**: Map `chat_heads` and `chat_messages` tables.

**Steps**:
1. Create `backend/models/chat_head.py`
2. Create `backend/models/chat_message.py`
3. Match existing table structure

---

#### Task 2.7: Create Remaining Models
**Status**: `[ ]`  
**Description**: Map remaining tables (company, event, task, patient, route_stage, etc.)

**Steps**:
1. Create models for: Company, Event, Task, Patient, PatientRecord, TreatmentRecord, Project, RouteStage, Gen
2. These are used by admin dashboard CRUD

---

### PHASE 3: Authentication & Middleware

#### Task 3.1: JWT Authentication System
**Status**: `[ ]`  
**Description**: Implement JWT auth that is **compatible with existing tokens** issued by Laravel.

**CRITICAL DECISION**: The Flutter app stores JWT tokens in SharedPreferences. When we switch backends, existing users will have Laravel-issued tokens. Two options:
- **Option A (Recommended)**: Use the same JWT secret key from Laravel so existing tokens remain valid
- **Option B**: Force all users to re-login (simpler but worse UX)

**Steps**:
1. Copy `utils/auth.py` from benchmark — the `@jwt_required_with_user` decorator pattern
2. Configure Flask-JWT-Extended with the same secret as Laravel
3. Laravel's `tymon/jwt-auth` uses HS256 by default — Flask-JWT-Extended also defaults to HS256 ✓

**Implementation** (from benchmark pattern):
```python
# utils/auth.py
from functools import wraps
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from models.user import AdminUser

def jwt_required_with_user(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        verify_jwt_in_request()
        user_id = get_jwt_identity()
        user = AdminUser.query.get(user_id)
        if not user:
            return jsonify({"code": 0, "message": "User not found"}), 401
        return f(user, *args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        verify_jwt_in_request()
        user_id = get_jwt_identity()
        user = AdminUser.query.get(user_id)
        if not user or user.user_type != 'Admin':
            return jsonify({"code": 0, "message": "Admin access required"}), 403
        return f(user, *args, **kwargs)
    return decorated
```

**⚠️ Laravel JWT Fallback**: The current Laravel backend has a **6-step token fallback chain** that also checks `user_id` parameter. The Python backend should replicate this for backward compatibility:
```
1. Authorization: {token}
2. Authorization: Bearer {token}
3. Authorization: Token {token}
4. token query parameter
5. token POST body
6. user_id POST body (legacy fallback)
```

---

#### Task 3.2: Response Format Helper
**Status**: `[ ]`  
**Description**: Create a standard response builder that matches Laravel's format exactly.

**Steps**:
1. Create `utils/response.py`

```python
# utils/response.py
from flask import jsonify

def success_response(message="Success", data=None, code=1, status_code=200):
    """Match Laravel's response format: {"code": 1, "message": "...", "data": {...}}"""
    response = {
        "code": code,
        "message": message,
    }
    if data is not None:
        response["data"] = data
    return jsonify(response), status_code

def error_response(message="Error", data=None, code=0, status_code=400):
    response = {
        "code": code,
        "message": message,
    }
    if data is not None:
        response["data"] = data
    return jsonify(response), status_code
```

---

#### Task 3.3: CORS Configuration
**Status**: `[ ]`  
**Description**: Configure CORS to allow requests from Flutter app and admin dashboard.

**Steps**:
1. Use Flask-CORS (from benchmark pattern)
2. Allow all origins for `/api/*` (matches Laravel's current open CORS)

---

### PHASE 4: Mobile API Endpoints

> **CRITICAL**: Every endpoint must return the EXACT same JSON structure that the Flutter app expects. Test against the actual Flutter code.

#### Task 4.1: Authentication Routes
**Status**: `[ ]`  
**Description**: Implement login, register, OTP endpoints.

**Endpoints to implement**:
| Method | Laravel Path | Flask Path | Handler |
|--------|-------------|------------|---------|
| POST | `/api/users/login` | `/api/users/login` | `auth.login()` |
| POST | `/api/users/register` | `/api/users/register` | `auth.register()` |
| POST | `/api/otp-request` | `/api/otp-request` | `auth.otp_request()` |
| POST | `/api/otp-verify` | `/api/otp-verify` | `auth.otp_verify()` |
| GET | `/api/users/me` | `/api/users/me` | `auth.me()` |

**Login response format** (must match exactly):
```json
{
  "code": 1,
  "message": "Login successful",
  "data": {
    "token": "eyJ...",
    "user": {
      "id": 1,
      "username": "john",
      "name": "John Doe",
      "first_name": "John",
      "last_name": "Doe",
      "email": "john@example.com",
      "phone_number": "+14165551234",
      "avatar": "uploads/profiles/1.jpg",
      "user_type": "Customer",
      "status": "1",
      ...all other user fields
    }
  }
}
```

**Steps**:
1. Create `routes/auth.py` blueprint
2. Implement `POST /api/users/login` — validate email/phone + password using `bcrypt.checkpw()`
3. Implement `POST /api/users/register` — create user, hash password, return token
4. Implement `POST /api/otp-request` — send OTP via SMS
5. Implement `POST /api/otp-verify` — verify OTP code
6. Implement `GET /api/users/me` — return current user from JWT

---

#### Task 4.2: Profile Routes
**Status**: `[ ]`  
**Description**: Implement profile management endpoints.

**Endpoints to implement**:
| Method | Path | Handler |
|--------|------|---------|
| POST | `/api/profile/update` | `profile.update()` |
| POST | `/api/profile/avatar` | `profile.upload_avatar()` |
| POST | `/api/profile/update-email` | `profile.update_email()` |
| POST | `/api/profile/update-phone` | `profile.update_phone()` |
| POST | `/api/profile/change-password` | `profile.change_password()` |
| POST | `/api/profile/delete-account` | `profile.delete_account()` |
| POST | `/api/become-driver` | `profile.become_driver()` |

**Steps**:
1. Create `routes/profile.py` blueprint
2. Implement each endpoint matching Laravel's `ProfileController` logic
3. File uploads for avatar and driver license must use same path convention
4. `delete-account` must soft-delete (set `status='Deleted'`, `deleted_at=now()`)

---

#### Task 4.3: Trip Routes
**Status**: `[ ]`  
**Description**: Implement trip management endpoints.

**Endpoints to implement**:
| Method | Path | Handler |
|--------|------|---------|
| GET | `/api/trips` | `trips.index()` |
| POST | `/api/trips-create` | `trips.create()` |
| POST | `/api/trips-update` | `trips.update()` |
| POST | `/api/trips-drivers` | `trips.get_drivers()` |
| GET | `/api/trips-driver-bookings` | `trips.driver_bookings()` |
| POST | `/api/trips-bookings-create` | `trips.create_booking()` |
| POST | `/api/trips-bookings-update` | `trips.update_booking()` |
| POST | `/api/trips-booking-status-update` | `trips.update_booking_status()` |
| POST | `/api/get-available-trips` | `trips.search_available()` |

**Steps**:
1. Create `routes/trips.py` blueprint
2. Port all trip logic from Laravel `ApiAuthController` (many trip methods live there)
3. Trip search uses lat/lng distance calculations — port the Haversine formula from `Utils.php`

---

#### Task 4.4: Negotiation Routes
**Status**: `[ ]`  
**Description**: Implement the real-time negotiation system.

**Endpoints to implement**:
| Method | Path | Handler |
|--------|------|---------|
| GET | `/api/negotiations` | `negotiations.index()` |
| POST | `/api/negotiations-create` | `negotiations.create()` |
| POST | `/api/negotiation-updates` | `negotiations.poll_updates()` |
| POST | `/api/negotiations-records` | `negotiations.add_record()` |
| POST | `/api/negotiations-accept` | `negotiations.accept()` |
| POST | `/api/negotiations-cancel` | `negotiations.cancel()` |
| POST | `/api/negotiation-status-change` | `negotiations.change_status()` |
| POST | `/api/negotiations-complete` | `negotiations.complete()` |
| GET | `/api/negotiations-records` | `negotiations.get_records()` |
| POST | `/api/negotiations-refresh-payment` | `negotiations.refresh_payment()` |
| POST | `/api/negotiations-check-payment` | `negotiations.check_payment()` |

**Steps**:
1. Create `routes/negotiations.py` blueprint
2. Port negotiation logic from `ApiNegotiationController` and `ApiChatController`
3. Payment link generation must use Stripe Checkout Session exactly as Laravel does
4. Poll updates endpoint is called every ~10 seconds by the Flutter app — optimize for performance

---

#### Task 4.5: Booking Routes (Scheduled/On-Demand)
**Status**: `[ ]`  
**Description**: Implement booking endpoints for scheduled and on-demand rides.

**Endpoints to implement**:
| Method | Path | Handler |
|--------|------|---------|
| GET | `/api/bookings` | `bookings.index()` |
| POST | `/api/bookings` | `bookings.create()` |
| GET | `/api/bookings/{id}` | `bookings.show()` |
| POST | `/api/bookings/{id}/cancel` | `bookings.cancel()` |
| POST | `/api/bookings/{id}/accept-price` | `bookings.accept_price()` |
| POST | `/api/bookings/{id}/accept-original-price` | `bookings.accept_original()` |
| POST | `/api/bookings/{id}/propose-price` | `bookings.propose_price()` |
| POST | `/api/bookings/{id}/start` | `bookings.start()` |
| POST | `/api/bookings/{id}/complete` | `bookings.complete()` |
| POST | `/api/bookings/{id}/assign-driver` | `bookings.assign_driver()` |
| POST | `/api/bookings/{id}/refresh-payment` | `bookings.refresh_payment()` |
| POST | `/api/bookings/{id}/check-payment` | `bookings.check_payment()` |
| POST | `/api/bookings/{id}/mark-paid` | `bookings.mark_paid()` |

**Steps**:
1. Create `routes/bookings.py` blueprint
2. Port booking logic from `ApiBookingController`
3. Prices stored in CENTS — maintain same conversion logic
4. Stripe payment link generation for bookings

---

#### Task 4.6: Wallet Routes
**Status**: `[ ]`  
**Description**: Implement wallet/earnings endpoints.

**Endpoints to implement**:
| Method | Path | Handler |
|--------|------|---------|
| GET | `/api/wallet` | `wallet.index()` |
| GET | `/api/wallet/transactions` | `wallet.transactions()` |
| GET | `/api/wallet/summary` | `wallet.summary()` |
| GET | `/api/wallet/earnings` | `wallet.earnings()` |

**Steps**:
1. Create `routes/wallet.py` blueprint
2. Port logic from `WalletController`
3. Balance calculations must match exactly

---

#### Task 4.7: Payout Account Routes
**Status**: `[ ]`  
**Description**: Implement Stripe Connect payout account management.

**Endpoints to implement**:
| Method | Path | Handler |
|--------|------|---------|
| GET | `/api/payout-account` | `payout_account.show()` |
| POST | `/api/payout-account/create-stripe` | `payout_account.create_stripe()` |
| POST | `/api/payout-account/onboarding-link` | `payout_account.onboarding_link()` |
| GET | `/api/payout-account/dashboard-link` | `payout_account.dashboard_link()` |
| POST | `/api/payout-account/sync` | `payout_account.sync()` |
| POST | `/api/payout-account/preferences` | `payout_account.preferences()` |
| POST | `/api/payout-account/deactivate` | `payout_account.deactivate()` |
| POST | `/api/payout-account/reactivate` | `payout_account.reactivate()` |

**Steps**:
1. Create `routes/payout_account.py` blueprint
2. Port logic from `PayoutAccountController`
3. Stripe Connect API calls must use same parameters

---

#### Task 4.8: Payout Request Routes
**Status**: `[ ]`  
**Description**: Implement driver payout withdrawal requests.

**Endpoints to implement**:
| Method | Path | Handler |
|--------|------|---------|
| GET | `/api/payout-requests` | `payout_requests.index()` |
| GET | `/api/payout-requests/statistics` | `payout_requests.statistics()` |
| POST | `/api/payout-requests` | `payout_requests.create()` |
| GET | `/api/payout-requests/{id}` | `payout_requests.show()` |
| POST | `/api/payout-requests/{id}/cancel` | `payout_requests.cancel()` |

**Steps**:
1. Create `routes/payout_requests.py` blueprint
2. Port logic from `PayoutRequestController`

---

#### Task 4.9: Chat Routes
**Status**: `[ ]`  
**Description**: Implement chat/messaging endpoints.

**Endpoints to implement**:
| Method | Path | Handler |
|--------|------|---------|
| GET | `/api/chat-heads` | `chat.get_heads()` |
| POST | `/api/chat-heads-create` | `chat.create_head()` |
| GET | `/api/chat-messages` | `chat.get_messages()` |
| POST | `/api/chat-send` | `chat.send_message()` |

**Steps**:
1. Create `routes/chat.py` blueprint
2. Port logic from `ApiChatController`

---

#### Task 4.10: Location & Status Routes
**Status**: `[ ]`  
**Description**: Implement location tracking and driver status endpoints.

**Endpoints to implement**:
| Method | Path | Handler |
|--------|------|---------|
| POST | `/api/update-location` | `location.update()` |
| POST | `/api/go-on-off` | `location.toggle_online()` |
| GET | `/api/trip-notes` | `location.get_notes()` |
| POST | `/api/trip-notes-add` | `location.add_note()` |
| GET | `/api/important-contacts` | `location.important_contacts()` |

---

#### Task 4.11: Resource Routes
**Status**: `[ ]`  
**Description**: Implement resource/lookup endpoints (drivers, SACCOs, etc.)

**Endpoints to implement**:
| Method | Path | Handler |
|--------|------|---------|
| GET | `/api/saccos` | `resources.saccos()` |
| GET | `/api/drivers` | `resources.drivers()` |
| POST | `/api/rideshare-refresh-payment` | `resources.rideshare_refresh_payment()` |
| POST | `/api/rideshare-check-payment` | `resources.rideshare_check_payment()` |

---

#### Task 4.12: Stripe Webhook
**Status**: `[ ]`  
**Description**: Implement Stripe webhook handler for payment callbacks.

**Endpoint**: `POST /api/stripe-webhook`

**Steps**:
1. Create `routes/webhooks.py`
2. Verify Stripe signature
3. Handle events: `checkout.session.completed`, `payment_intent.succeeded`, `payment_intent.payment_failed`
4. Update negotiation/booking payment_status accordingly
5. Credit driver wallet on successful payment

---

### PHASE 5: Admin Dashboard (API + React UI)

#### Task 5.1: Copy Admin UI from Benchmark
**Status**: `[ ]`  
**Description**: Copy the React admin panel from the benchmark project and adapt it.

**Steps**:
1. Copy entire `frontend/` directory from benchmark
2. Strip VoIP-specific components (CallOverlay, DeviceSettings, etc.)
3. Keep: AdminPanel, auth system, API service, contexts, Navbar
4. Add new components for NegoRide-specific CRUD:
   - UserManagement (Drivers + Customers with approval workflow)
   - TripManagement
   - NegotiationManagement
   - BookingManagement
   - PaymentManagement
   - WalletManagement

---

#### Task 5.2: Admin Dashboard API
**Status**: `[ ]`  
**Description**: Implement admin API endpoints.

**Endpoints to implement**:
| Method | Path | Handler |
|--------|------|---------|
| GET | `/api/admin/dashboard` | `admin.dashboard()` |
| GET | `/api/admin/users` | `admin.list_users()` |
| PUT | `/api/admin/users/{id}` | `admin.update_user()` |
| GET | `/api/admin/users/{id}/approve` | `admin.approve_user()` |
| GET | `/api/admin/users/{id}/block` | `admin.block_user()` |
| GET | `/api/admin/users/{id}/activate` | `admin.activate_user()` |
| GET | `/api/admin/users/{id}/approve-service/{service}` | `admin.approve_service()` |
| GET/POST/PUT/DELETE | `/api/admin/negotiations/*` | `admin.negotiations_crud()` |
| GET/POST/PUT/DELETE | `/api/admin/trips/*` | `admin.trips_crud()` |
| GET/POST/PUT/DELETE | `/api/admin/bookings/*` | `admin.bookings_crud()` |
| GET/POST/PUT/DELETE | `/api/admin/companies/*` | `admin.companies_crud()` |
| GET/POST/PUT/DELETE | `/api/admin/events/*` | `admin.events_crud()` |
| GET/POST/PUT/DELETE | `/api/admin/tasks/*` | `admin.tasks_crud()` |
| GET/POST/PUT/DELETE | `/api/admin/route-stages/*` | `admin.route_stages_crud()` |

**Steps**:
1. Create `routes/admin.py` blueprint
2. Implement dashboard stats (total users, trips, revenue, etc.)
3. Implement CRUD for each resource matching Encore Admin's behavior
4. Add pagination matching Laravel's format

---

#### Task 5.3: Admin Authentication
**Status**: `[ ]`  
**Description**: Implement admin login that supports email, username, and phone.

**Steps**:
1. Reuse JWT auth from Task 3.1
2. Admin login endpoint at `/api/admin/auth/login` (or reuse `/api/users/login` with role check)
3. Add `@admin_required` decorator for admin-only endpoints

---

### PHASE 6: Stripe Payment Integration

#### Task 6.1: Stripe Service
**Status**: `[ ]`  
**Description**: Create a Stripe service module that handles all payment operations.

**Steps**:
1. Create `services/stripe_service.py`
2. Implement:
   - `create_payment_link(amount_cents, description, metadata)` — Stripe Checkout Session
   - `check_payment_status(stripe_session_id)` — Check if paid
   - `process_webhook(payload, signature)` — Verify and handle webhook events
   - `create_connect_account(user)` — Stripe Connect for drivers
   - `create_onboarding_link(account_id)` — Account onboarding URL
   - `create_payout(account_id, amount)` — Transfer to driver
3. Use same Stripe API version as Laravel

**⚠️ LIVE KEYS**: The system uses **live Stripe keys** — handle with extreme care during testing.

---

#### Task 6.2: Wallet Service
**Status**: `[ ]`  
**Description**: Create wallet business logic service.

**Steps**:
1. Create `services/wallet_service.py`
2. Implement:
   - `credit_driver_wallet(driver_id, amount, negotiation_id)` — After payment received
   - `debit_service_fee(amount)` — 10% service fee deduction
   - `process_payout(user_id, amount)` — Withdraw to bank
   - `get_balance(user_id)` — Current balance
   - `get_transactions(user_id, filters)` — Transaction history

---

### PHASE 7: File Uploads & Storage

#### Task 7.1: File Upload Handler
**Status**: `[ ]`  
**Description**: Implement file upload handling for profile photos and documents.

**Steps**:
1. Use Flask's `request.files` (from benchmark pattern)
2. Store files in `uploads/` directory with same path structure as Laravel
3. Serve uploaded files via `/uploads/<path>` route
4. Handle image resizing for avatars (optional, use Pillow)

**Upload paths must match Laravel**:
- Profile avatars: `uploads/images/<filename>`
- Driver documents: `uploads/images/<filename>`
- File served at: `{APP_URL}/storage/<path>` or `{APP_URL}/uploads/<path>`

---

### PHASE 8: Push Notifications (OneSignal)

#### Task 8.1: OneSignal Integration
**Status**: `[ ]`  
**Description**: Implement push notification sending via OneSignal REST API.

**Steps**:
1. Create `services/notification_service.py`
2. Port `Utils::sendNotification()` from Laravel
3. Send notifications on:
   - New negotiation request
   - Negotiation accepted/rejected
   - Booking created/updated/cancelled
   - Payment received
   - Driver assigned

**OneSignal API call**:
```python
import requests

def send_notification(user_ids, heading, message, data=None):
    """Send push via OneSignal REST API"""
    payload = {
        "app_id": ONESIGNAL_APP_ID,
        "include_external_user_ids": user_ids,
        "headings": {"en": heading},
        "contents": {"en": message},
    }
    if data:
        payload["data"] = data
    
    headers = {
        "Authorization": f"Basic {ONESIGNAL_REST_API_KEY}",
        "Content-Type": "application/json"
    }
    requests.post("https://onesignal.com/api/v1/notifications", json=payload, headers=headers)
```

---

### PHASE 9: Testing & Validation

#### Task 9.1: Endpoint Comparison Testing
**Status**: `[ ]`  
**Description**: Run both Laravel and Python backends simultaneously and compare responses.

**Steps**:
1. Run Laravel on port 8888 (MAMP default)
2. Run Python on port 5000
3. For each endpoint:
   - Send identical request to both
   - Compare JSON responses field-by-field
   - Verify status codes match
   - Verify error responses match

**Test script template**:
```python
import requests
import json

LARAVEL_URL = "http://localhost:8888/negoride-canada-api/api"
PYTHON_URL = "http://localhost:5000/api"

def compare_endpoint(method, path, data=None, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    if method == 'GET':
        r1 = requests.get(f"{LARAVEL_URL}{path}", headers=headers)
        r2 = requests.get(f"{PYTHON_URL}{path}", headers=headers)
    else:
        r1 = requests.post(f"{LARAVEL_URL}{path}", json=data, headers=headers)
        r2 = requests.post(f"{PYTHON_URL}{path}", json=data, headers=headers)
    
    assert r1.status_code == r2.status_code, f"Status mismatch: {r1.status_code} vs {r2.status_code}"
    assert r1.json() == r2.json(), f"Response mismatch:\nLaravel: {r1.json()}\nPython: {r2.json()}"
    print(f"✓ {method} {path}")
```

---

#### Task 9.2: Flutter App Testing
**Status**: `[ ]`  
**Description**: Point the Flutter app at the Python backend and test all flows.

**Steps**:
1. Change API base URL in Flutter to point to Python backend
2. Test complete flows:
   - Register → Login → Update profile → Upload avatar
   - Create trip → Search trips → Book trip → Pay
   - Start negotiation → Send messages → Accept → Pay
   - Create scheduled booking → Assign driver → Start → Complete
   - View wallet → Request payout
   - Chat with driver/customer
   - Delete account
3. Fix any response format discrepancies

---

#### Task 9.3: Admin Dashboard Testing
**Status**: `[ ]`  
**Description**: Test all admin panel functionality.

**Steps**:
1. Login as admin
2. Test: Dashboard stats, user CRUD, driver approval, trip management, negotiation views, payment views
3. Verify all data displays correctly

---

### PHASE 10: Deployment & Cutover

#### Task 10.1: Production Server Setup
**Status**: `[ ]`  
**Description**: Deploy Python backend to production server.

**Steps**:
1. Install Python 3.11+ on production server
2. Set up virtual environment
3. Install dependencies from requirements.txt
4. Configure Gunicorn as WSGI server
5. Configure Nginx as reverse proxy
6. Set up SSL certificate
7. Configure environment variables

**Gunicorn command**:
```bash
gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 app:app
```

---

#### Task 10.2: React Admin Build
**Status**: `[ ]`  
**Description**: Build and deploy the React admin panel.

**Steps**:
1. `cd frontend && npm run build`
2. Serve static build via Flask or Nginx
3. Configure API proxy

---

#### Task 10.3: DNS & Route Cutover
**Status**: `[ ]`  
**Description**: Switch production traffic from Laravel to Python.

**Steps**:
1. Final comparison test on production data
2. Put Laravel in maintenance mode
3. Update Nginx to route to Python backend
4. Verify Flutter app works
5. Monitor for errors
6. Keep Laravel running as fallback for 1 week

---

## 4. Response Format Contract

The Flutter app expects ALL API responses in this exact format:

### Success Response
```json
{
  "code": 1,
  "message": "Description of success",
  "data": {
    // Response payload (varies per endpoint)
  }
}
```

### Error Response
```json
{
  "code": 0,
  "message": "Description of error",
  "data": null
}
```

### Pagination Response
```json
{
  "code": 1,
  "message": "Success",
  "data": {
    "current_page": 1,
    "data": [...items...],
    "per_page": 15,
    "total": 100,
    "last_page": 7
  }
}
```

### Key Rules:
- `code` is always `1` for success, `0` for error (integer, not boolean)
- `message` is always a string
- `data` contains the actual payload
- Dates format: `"2026-04-13 10:30:00"` (Y-m-d H:i:s)
- Prices: integers in cents where noted (e.g., `2800` = $28.00)
- Boolean fields: some use `"Yes"/"No"` strings, some use actual `true/false`

---

## 5. Endpoint Mapping (Laravel → Python)

### Complete Endpoint List (70+ endpoints)

| # | Method | URL Path | Laravel Controller | Python Route File | Priority |
|---|--------|----------|-------------------|-------------------|----------|
| 1 | POST | `/api/users/login` | ApiAuthController@login | routes/auth.py | 🔴 HIGH |
| 2 | POST | `/api/users/register` | ApiAuthController@register | routes/auth.py | 🔴 HIGH |
| 3 | POST | `/api/otp-request` | ApiAuthController@otpRequest | routes/auth.py | 🟡 MED |
| 4 | POST | `/api/otp-verify` | ApiAuthController@otpVerify | routes/auth.py | 🟡 MED |
| 5 | GET | `/api/users/me` | ApiAuthController@me | routes/auth.py | 🔴 HIGH |
| 6 | POST | `/api/profile/update` | ProfileController@update | routes/profile.py | 🔴 HIGH |
| 7 | POST | `/api/profile/avatar` | ProfileController@uploadAvatar | routes/profile.py | 🟡 MED |
| 8 | POST | `/api/profile/update-email` | ProfileController@updateEmail | routes/profile.py | 🟡 MED |
| 9 | POST | `/api/profile/update-phone` | ProfileController@updatePhone | routes/profile.py | 🟡 MED |
| 10 | POST | `/api/profile/change-password` | ProfileController@changePassword | routes/profile.py | 🟡 MED |
| 11 | POST | `/api/profile/delete-account` | ProfileController@deleteAccount | routes/profile.py | 🔴 HIGH |
| 12 | POST | `/api/become-driver` | ApiAuthController@becomeDriver | routes/profile.py | 🟡 MED |
| 13 | GET | `/api/trips` | ApiAuthController@getTrips | routes/trips.py | 🔴 HIGH |
| 14 | POST | `/api/trips-create` | ApiAuthController@createTrip | routes/trips.py | 🔴 HIGH |
| 15 | POST | `/api/trips-update` | ApiAuthController@updateTrip | routes/trips.py | 🔴 HIGH |
| 16 | POST | `/api/trips-drivers` | ApiAuthController@getTripDrivers | routes/trips.py | 🔴 HIGH |
| 17 | GET | `/api/trips-driver-bookings` | ApiAuthController@driverBookings | routes/trips.py | 🔴 HIGH |
| 18 | POST | `/api/trips-bookings-create` | ApiAuthController@createBooking | routes/trips.py | 🔴 HIGH |
| 19 | POST | `/api/trips-bookings-update` | ApiAuthController@updateBooking | routes/trips.py | 🟡 MED |
| 20 | POST | `/api/trips-booking-status-update` | ApiAuthController@updateBookingStatus | routes/trips.py | 🔴 HIGH |
| 21 | POST | `/api/get-available-trips` | ApiResurceController@getAvailableTrips | routes/trips.py | 🔴 HIGH |
| 22 | GET | `/api/negotiations` | ApiNegotiationController@index | routes/negotiations.py | 🔴 HIGH |
| 23 | POST | `/api/negotiations-create` | ApiNegotiationController@create | routes/negotiations.py | 🔴 HIGH |
| 24 | POST | `/api/negotiation-updates` | ApiChatController@getNegotiationUpdates | routes/negotiations.py | 🔴 HIGH |
| 25 | POST | `/api/negotiations-records` | ApiChatController@addRecord | routes/negotiations.py | 🔴 HIGH |
| 26 | POST | `/api/negotiations-accept` | ApiNegotiationController@accept | routes/negotiations.py | 🔴 HIGH |
| 27 | POST | `/api/negotiations-cancel` | ApiNegotiationController@cancel | routes/negotiations.py | 🔴 HIGH |
| 28 | POST | `/api/negotiation-status-change` | ApiNegotiationController@statusChange | routes/negotiations.py | 🔴 HIGH |
| 29 | POST | `/api/negotiations-complete` | ApiNegotiationController@complete | routes/negotiations.py | 🔴 HIGH |
| 30 | GET | `/api/negotiations-records` | ApiChatController@getRecords | routes/negotiations.py | 🔴 HIGH |
| 31 | POST | `/api/negotiations-refresh-payment` | ApiChatController@refreshPayment | routes/negotiations.py | 🔴 HIGH |
| 32 | POST | `/api/negotiations-check-payment` | ApiChatController@checkPayment | routes/negotiations.py | 🔴 HIGH |
| 33 | GET | `/api/bookings` | ApiBookingController@index | routes/bookings.py | 🔴 HIGH |
| 34 | POST | `/api/bookings` | ApiBookingController@store | routes/bookings.py | 🔴 HIGH |
| 35 | GET | `/api/bookings/{id}` | ApiBookingController@show | routes/bookings.py | 🟡 MED |
| 36 | POST | `/api/bookings/{id}/cancel` | ApiBookingController@cancel | routes/bookings.py | 🟡 MED |
| 37 | POST | `/api/bookings/{id}/accept-price` | ApiBookingController@acceptPrice | routes/bookings.py | 🔴 HIGH |
| 38 | POST | `/api/bookings/{id}/accept-original-price` | ApiBookingController@acceptOriginal | routes/bookings.py | 🟡 MED |
| 39 | POST | `/api/bookings/{id}/propose-price` | ApiBookingController@proposePrice | routes/bookings.py | 🔴 HIGH |
| 40 | POST | `/api/bookings/{id}/start` | ApiBookingController@start | routes/bookings.py | 🔴 HIGH |
| 41 | POST | `/api/bookings/{id}/complete` | ApiBookingController@complete | routes/bookings.py | 🔴 HIGH |
| 42 | POST | `/api/bookings/{id}/assign-driver` | ApiBookingController@assignDriver | routes/bookings.py | 🟡 MED |
| 43 | POST | `/api/bookings/{id}/refresh-payment` | ApiBookingController@refreshPayment | routes/bookings.py | 🔴 HIGH |
| 44 | POST | `/api/bookings/{id}/check-payment` | ApiBookingController@checkPayment | routes/bookings.py | 🔴 HIGH |
| 45 | POST | `/api/bookings/{id}/mark-paid` | ApiBookingController@markPaid | routes/bookings.py | 🟡 MED |
| 46 | GET | `/api/wallet` | WalletController@index | routes/wallet.py | 🔴 HIGH |
| 47 | GET | `/api/wallet/transactions` | WalletController@transactions | routes/wallet.py | 🔴 HIGH |
| 48 | GET | `/api/wallet/summary` | WalletController@summary | routes/wallet.py | 🟡 MED |
| 49 | GET | `/api/wallet/earnings` | WalletController@earnings | routes/wallet.py | 🟡 MED |
| 50 | GET | `/api/payout-account` | PayoutAccountController@show | routes/payout_account.py | 🔴 HIGH |
| 51 | POST | `/api/payout-account/create-stripe` | PayoutAccountController@createStripe | routes/payout_account.py | 🔴 HIGH |
| 52 | POST | `/api/payout-account/onboarding-link` | PayoutAccountController@onboardingLink | routes/payout_account.py | 🔴 HIGH |
| 53 | GET | `/api/payout-account/dashboard-link` | PayoutAccountController@dashboardLink | routes/payout_account.py | 🟡 MED |
| 54 | POST | `/api/payout-account/sync` | PayoutAccountController@sync | routes/payout_account.py | 🟡 MED |
| 55 | POST | `/api/payout-account/preferences` | PayoutAccountController@preferences | routes/payout_account.py | 🟢 LOW |
| 56 | POST | `/api/payout-account/deactivate` | PayoutAccountController@deactivate | routes/payout_account.py | 🟢 LOW |
| 57 | POST | `/api/payout-account/reactivate` | PayoutAccountController@reactivate | routes/payout_account.py | 🟢 LOW |
| 58 | GET | `/api/payout-requests` | PayoutRequestController@index | routes/payout_requests.py | 🔴 HIGH |
| 59 | GET | `/api/payout-requests/statistics` | PayoutRequestController@statistics | routes/payout_requests.py | 🟡 MED |
| 60 | POST | `/api/payout-requests` | PayoutRequestController@store | routes/payout_requests.py | 🔴 HIGH |
| 61 | GET | `/api/payout-requests/{id}` | PayoutRequestController@show | routes/payout_requests.py | 🟡 MED |
| 62 | POST | `/api/payout-requests/{id}/cancel` | PayoutRequestController@cancel | routes/payout_requests.py | 🟡 MED |
| 63 | GET | `/api/chat-heads` | ApiChatController@getChatHeads | routes/chat.py | 🔴 HIGH |
| 64 | POST | `/api/chat-heads-create` | ApiChatController@createChatHead | routes/chat.py | 🟡 MED |
| 65 | GET | `/api/chat-messages` | ApiChatController@getChatMessages | routes/chat.py | 🔴 HIGH |
| 66 | POST | `/api/chat-send` | ApiChatController@sendChat | routes/chat.py | 🔴 HIGH |
| 67 | POST | `/api/update-location` | ApiAuthController@updateLocation | routes/location.py | 🔴 HIGH |
| 68 | POST | `/api/go-on-off` | ApiAuthController@goOnOff | routes/location.py | 🟡 MED |
| 69 | GET | `/api/trip-notes` | ApiAuthController@getTripNotes | routes/location.py | 🟡 MED |
| 70 | POST | `/api/trip-notes-add` | ApiAuthController@addTripNote | routes/location.py | 🟡 MED |
| 71 | GET | `/api/important-contacts` | ApiResurceController@importantContacts | routes/resources.py | 🟢 LOW |
| 72 | GET | `/api/saccos` | ApiResurceController@getSaccos | routes/resources.py | 🟢 LOW |
| 73 | GET | `/api/drivers` | ApiResurceController@getDrivers | routes/resources.py | 🟡 MED |
| 74 | POST | `/api/rideshare-refresh-payment` | ApiResurceController@rideshareRefresh | routes/resources.py | 🔴 HIGH |
| 75 | POST | `/api/rideshare-check-payment` | ApiResurceController@rideshareCheck | routes/resources.py | 🔴 HIGH |
| 76 | POST | `/api/stripe-webhook` | ApiChatController@stripeWebhook | routes/webhooks.py | 🔴 HIGH |

---

## 6. Database Schema Reference

> **No schema changes needed.** The Python backend connects to the SAME `negoride` MySQL database.

### 6.1 admin_users
| Column | Type | Notes |
|--------|------|-------|
| id | int (PK) | Auto-increment |
| username | varchar(190) | Unique |
| name | varchar(255) | Full name |
| first_name | varchar(255) | Nullable |
| last_name | varchar(255) | Nullable |
| email | varchar(255) | Nullable |
| phone_number | varchar(255) | With country code |
| phone_number_2 | varchar(255) | Nullable |
| password | varchar(60) | bcrypt hash |
| avatar | varchar(255) | File path |
| remember_token | varchar(100) | Session token |
| country_name | varchar(50) | Default: Canada |
| country_code | varchar(5) | Default: +1 |
| country_short_name | varchar(3) | Default: CA |
| date_of_birth | date | Nullable |
| place_of_birth | varchar(255) | Nullable |
| sex | enum(Male,Female) | Nullable |
| home_address | text | Nullable |
| current_address | text | Nullable |
| user_type | enum(Admin,Driver,Pending Driver,Customer) | Default: Customer |
| status | enum(0,1,2) | 0=blocked, 1=active, 2=pending |
| ready_for_trip | enum(Yes,No) | Default: No |
| enterprise_id | varchar(255) | Nullable |
| nin | varchar(255) | National ID |
| driving_license_* | various | License info fields |
| is_car...is_firebrugade | enum(Yes,No) | Service capabilities |
| is_car_approved...is_firebrugade_approved | enum(Yes,No) | Admin approvals |
| latitude | varchar(255) | Current GPS lat |
| longitude | varchar(255) | Current GPS lng |
| created_at | timestamp | |
| updated_at | timestamp | |
| deleted_at | timestamp | Soft delete |

### 6.2 negotiations
| Column | Type | Notes |
|--------|------|-------|
| id | bigint (PK) | Auto-increment |
| customer_id | int | FK to admin_users |
| customer_name | text | Nullable |
| driver_id | int | FK to admin_users |
| driver_name | text | Nullable |
| status | varchar | Default: Pending |
| is_active | boolean | Default: true |
| customer_accepted | varchar | Default: Pending |
| customer_driver | varchar | Default: Pending |
| pickup_lat/lng/address | text | Pickup location |
| dropoff_lat/lng/address | text | Dropoff location |
| initial_price | int | In CENTS |
| agreed_price | decimal(10,2) | In DOLLARS |
| payment_status | enum | unpaid/pending/paid/failed/refunded |
| payment_id | bigint | FK to payments |
| stripe_id | varchar | Stripe session ID |
| stripe_session_id | varchar | |
| stripe_paid | varchar | Yes/No |
| created_at/updated_at | timestamps | |

### 6.3 negotiation_records
| Column | Type | Notes |
|--------|------|-------|
| id | bigint (PK) | |
| negotiation_id | int | |
| customer_id | int | |
| driver_id | int | |
| last_negotiator_id | int | |
| first_negotiator_id | int | |
| price_accepted | varchar | Yes/No |
| price | int | In CENTS |
| message_type | varchar | Default: Negotiation |
| message_body | text | |
| is_received/is_seen | varchar | Yes/No |
| latitude/longitude | varchar | |
| created_at/updated_at | timestamps | |

### 6.4 payments
| Column | Type | Notes |
|--------|------|-------|
| id | bigint (PK) | |
| negotiation_id | bigint | FK |
| customer_id | bigint | FK |
| driver_id | bigint | FK |
| stripe_payment_intent_id | varchar | Unique |
| amount | decimal(10,2) | Total in CAD |
| service_fee | decimal(10,2) | Platform fee |
| driver_amount | decimal(10,2) | Driver receives |
| status | enum | pending/processing/succeeded/failed/etc |
| payment_type | enum | ride_payment/wallet_topup/refund |
| currency | varchar(3) | Default: cad |
| created_at/updated_at | timestamps | |

### 6.5 transactions
| Column | Type | Notes |
|--------|------|-------|
| id | bigint (PK) | |
| user_id | bigint | FK |
| user_type | enum | customer/driver |
| type | enum | credit/debit |
| category | enum | ride_payment/ride_earning/service_fee/etc |
| amount | decimal(10,2) | |
| balance_before/after | decimal(10,2) | |
| reference | varchar | Unique |
| status | enum | pending/completed/failed/reversed |
| created_at/updated_at | timestamps | |

### 6.6 user_wallets
| Column | Type | Notes |
|--------|------|-------|
| id | bigint (PK) | |
| user_id | bigint | Unique FK |
| wallet_balance | decimal(10,2) | Current balance |
| total_earnings | decimal(10,2) | Lifetime earnings |
| stripe_customer_id | varchar | |
| stripe_account_id | varchar | |
| created_at/updated_at | timestamps | |

### 6.7 payout_accounts
(See Phase 2, Task 2.5 for full schema — 40+ columns for Stripe Connect)

### 6.8 payout_requests
(See Phase 2, Task 2.5 for full schema)

### 6.9 scheduled_bookings
| Column | Type | Notes |
|--------|------|-------|
| id | bigint (PK) | |
| customer_id | bigint | FK |
| driver_id | bigint | Nullable FK |
| service_type | varchar(100) | NegoRide, Airport Pickup, etc. |
| pickup_lat/lng | decimal(10,7) | |
| pickup_address | varchar(500) | |
| destination_lat/lng | decimal(10,7) | |
| destination_address | varchar(500) | |
| passengers | tinyint | Default: 1 |
| luggage | tinyint | Default: 0 |
| scheduled_at | datetime | |
| customer_proposed_price | bigint | In CENTS |
| driver_proposed_price | bigint | In CENTS, nullable |
| agreed_price | bigint | In CENTS, nullable |
| status | varchar(50) | Default: pending |
| payment_status | varchar(50) | Default: unpaid |
| stripe_id/stripe_url/stripe_paid | various | Stripe fields |
| created_at/updated_at | timestamps | |

### 6.10 trips
Standard trip table with route info, timing, driver assignment, status.

### 6.11 trip_bookings
Booking records for trips with Stripe payment integration fields.

### 6.12 trip_notes
Notes attached to trips (driver/passenger/system).

### 6.13 chat_heads, chat_messages
Messaging system tables.

---

## 7. Risk Register

| # | Risk | Impact | Mitigation |
|---|------|--------|------------|
| 1 | JWT token incompatibility | All users forced to re-login | Use same JWT secret and HS256 algorithm |
| 2 | bcrypt hash format difference ($2y$ vs $2b$) | Login failures | Python bcrypt handles both — verified compatible |
| 3 | Response format mismatch | Flutter app crashes | Endpoint comparison test suite (Phase 9) |
| 4 | Stripe webhook signature changes | Payments break | Keep same webhook secret, test thoroughly |
| 5 | File upload path mismatch | Profile photos break | Use exact same path convention |
| 6 | Live Stripe keys in production | Real money at risk | Test with test keys first, switch at cutover |
| 7 | Database connection pooling | Performance issues | Configure SQLAlchemy pool_size, max_overflow |
| 8 | Missing edge cases in ported logic | Subtle bugs | Port controller logic line-by-line, not rewrite |
| 9 | Admin dashboard feature gap | Admin can't manage data | Build admin panel features incrementally, keep Laravel admin as fallback |
| 10 | OneSignal notification format | Users miss notifications | Test notification payloads match exactly |

---

## Summary Statistics

- **Total API endpoints**: 76
- **High priority endpoints**: 42
- **Medium priority endpoints**: 24
- **Low priority endpoints**: 10
- **Database tables to model**: 15+
- **Total phases**: 10
- **Total tasks**: 35+

---

*Document created: 13 April 2026*  
*Last updated: 13 April 2026*  
*Author: Migration Planning Agent*
