1. Reasons to choose PostgreSQL:
    --> As it is mentioned in the statement that concurrent requests(we should not over book the event), a user can not book more than 2 tickets, to solve this 
    we need a database with strong ACID rules and enforce rules at database level , restricting user to not book the same seats that are already booked, and are released if the user cancelled it.

    we will be able to solve this using other DBs as well, but we will have to build the re-building transactional guarantees and constraints in application logic

    In my approch, i created seat level locking, and along with it SQLAlchemy provides "with_for_update(skip_locked=True)" 
    which help me to skip locked seats when concurrent transactions are being executed.


2. Other approaches to handle raceconditions:
    --> Transactions on event level(event_level_locking) I rejected it because it serializes every booking for that event. Even if two users are booking different seats, they still block each other, so throughput for a popular event becomes roughly one booking per transaction time. Under a spike, requests pile up behind the lock, causing high tail latency, timeouts, and connection pool exhaustion.

3. let's understand what every request does: locking read + updates seats +inserts a booking +commits DB cant do anywhere  near 1Million trasactions/sec.
for popular event even though we placed the lock seat constraint, over thousands of request come for same free seat available. those seats getting locked and updated by other transactions, so many requests end up skipping locked rows and end up nothing is available to book, there will be many wasted reads which slows everything.even though 1 transaction to db latency seems small for 1Million request the letency increases.
