-- For reference only

CREATE TABLE IF NOT EXISTS events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    total_tickets INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS seats (
    seat_id INTEGER NOT NULL,
    event_id UUID NOT NULL,
    is_booked BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (seat_id, event_id),
    FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bookings (
    booking_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL,
    seat_id1 INTEGER,
    seat_id2 INTEGER,
    user_id VARCHAR(255) NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE,
);


