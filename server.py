from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, select, func, delete, and_
from sqlalchemy.dialects.postgresql import UUID
import os
import uuid as uuid_lib
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://myuser:mypassword@localhost:5432/ticketing_db")

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

# Database Models
class Event(Base):
    __tablename__ = "events"
    
    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4)
    total_tickets = Column(Integer, nullable=False, default=100)
    
    seats = relationship("Seat", back_populates="event", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="event", cascade="all, delete-orphan")

class Seat(Base):
    __tablename__ = "seats"
    
    seat_id = Column(Integer, primary_key=True)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.event_id", ondelete="CASCADE"), primary_key=True)
    is_booked = Column(Boolean, nullable=False, default=False)
    
    event = relationship("Event", back_populates="seats")

class Booking(Base):
    __tablename__ = "bookings"
    
    booking_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False)
    seat_id1 = Column(Integer, nullable=True)
    seat_id2 = Column(Integer, nullable=True)
    user_id = Column(String(255), nullable=False)
    
    event = relationship("Event", back_populates="bookings")

# API Models
class TicketBooking(BaseModel):
    event_id: str
    user_id: str
    tickets: int = Field(gt=0, le=2, description="Number of tickets to book (max 2)")

class TicketCancel(BaseModel):
    booking_id: str

class EventResponse(BaseModel):
    event_id: str
    total_tickets: int

class BookingResponse(BaseModel):
    booking_id: str
    event_id: str
    user_id: str
    tickets: int
    timestamp: str

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(title="Ticketing Platform API", version="1.0.0", lifespan=lifespan)

@app.post("/events/initialize", response_model=EventResponse, status_code=201)
async def initialize_event(db: AsyncSession = Depends(get_db)):
    new_event = Event()
    db.add(new_event)
    await db.flush()
    
    seats = [Seat(seat_id=i, event_id=new_event.event_id, is_booked=False) 
             for i in range(1, new_event.total_tickets + 1)]
    db.add_all(seats)
    
    await db.commit()
    await db.refresh(new_event)
    
    return EventResponse(
        event_id=str(new_event.event_id),
        total_tickets=new_event.total_tickets
    )

@app.post("/tickets/book", response_model=BookingResponse, status_code=201)
async def book_ticket(booking: TicketBooking, db: AsyncSession = Depends(get_db)):
    try:
        event_uuid = uuid_lib.UUID(booking.event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid event_id format: {booking.event_id}")
    
    result = await db.execute(select(Event).where(Event.event_id == event_uuid))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {booking.event_id} not found")
    
    result = await db.execute(
        select(Booking)
        .where(Booking.event_id == event_uuid)
        .where(Booking.user_id == booking.user_id)
        .with_for_update()
    )
    user_bookings = result.scalars().all()
    current_user_tickets = sum(1 for b in user_bookings if b.seat_id1) + sum(1 for b in user_bookings if b.seat_id2)
    
    # Assumes concurrent requests from many users
    # But not concurrent requests from a single user
    if current_user_tickets + booking.tickets > 2:
        raise HTTPException(
            status_code=400,
            detail=f"User {booking.user_id} cannot book more than 2 tickets for event {booking.event_id}. "
                   f"Currently booked: {current_user_tickets}, requested: {booking.tickets}"
        )
    
    result = await db.execute(
        select(Seat)
        .where(and_(
            Seat.event_id == event_uuid,
            Seat.is_booked == False
        ))
        .order_by(Seat.seat_id)
        .limit(booking.tickets)
        .with_for_update(skip_locked=True)
    )
    available_seats = result.scalars().all()
    
    if len(available_seats) < booking.tickets:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough tickets available. Available: {len(available_seats)}, Requested: {booking.tickets}"
        )
    
    for seat in available_seats:
        seat.is_booked = True
    
    new_booking = Booking(
        event_id=event_uuid,
        user_id=booking.user_id,
        seat_id1=available_seats[0].seat_id if len(available_seats) > 0 else None,
        seat_id2=available_seats[1].seat_id if len(available_seats) > 1 else None
    )
    db.add(new_booking)
    await db.commit()
    await db.refresh(new_booking)
    
    return BookingResponse(
        booking_id=str(new_booking.booking_id),
        event_id=str(new_booking.event_id),
        user_id=new_booking.user_id,
        tickets=booking.tickets,
        timestamp=datetime.now().isoformat()
    )

@app.post("/tickets/cancel", response_model=dict, status_code=200)
async def cancel_ticket(cancel: TicketCancel, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Booking).where(Booking.booking_id == cancel.booking_id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail=f"Booking {cancel.booking_id} not found")
    
    event_id = booking.event_id
    
    if booking.seat_id1:
        result = await db.execute(
            select(Seat)
            .where(Seat.event_id == event_id)
            .where(Seat.seat_id == booking.seat_id1)
        )
        seat1 = result.scalar_one_or_none()
        if seat1:
            seat1.is_booked = False
    
    if booking.seat_id2:
        result = await db.execute(
            select(Seat)
            .where(Seat.event_id == event_id)
            .where(Seat.seat_id == booking.seat_id2)
        )
        seat2 = result.scalar_one_or_none()
        if seat2:
            seat2.is_booked = False
    
    await db.execute(delete(Booking).where(Booking.booking_id == cancel.booking_id))
    await db.commit()
    
    return {
        "message": "Ticket cancelled successfully",
        "booking_id": cancel.booking_id,
    }

@app.get("/events/{event_id}", response_model=EventResponse)
async def get_event(event_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Event).where(Event.event_id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    
    return EventResponse(
        event_id=str(event.event_id),
        total_tickets=event.total_tickets
    )

@app.get("/")
async def root():
    return {
        "message": "Ticketing Platform API",
        "endpoints": {
            "initialize_event": "POST /events/initialize",
            "book_ticket": "POST /tickets/book",
            "cancel_ticket": "POST /tickets/cancel",
            "get_event": "GET /events/{event_id}"
        }
    }
