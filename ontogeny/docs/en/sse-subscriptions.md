# Object change subscriptions

`GET /api/v1/subscriptions/objects/{object_type}` is an authenticated,
best-effort live notification feed, not a durable event log. Normal messages
contain identifiers only; read current values through the authorized query API.

Each subscriber has a bounded queue. If it overflows, the server discards that
subscriber's incomplete backlog, emits the named SSE event `resync_required`
with data `{"reason":"subscriber_overflow"}`, and ends the stream. Other
subscribers continue independently. Register an explicit listener for this
event: EventSource's default `onmessage` handler does not receive named events.

On this event, invalidate cached state. Re-establish the subscription before
fetching a fresh snapshot, and process or buffer notifications arriving during
the fetch so changes during recovery are not missed. If another overflow occurs,
repeat recovery. Resynchronize after other connection interruptions too: this
endpoint does not implement Last-Event-ID replay. Automatic reconnection alone
does not recover missed notifications.

The outbox SSE receipt records dispatch to the broker, not acknowledgement by
each remote subscriber. The resync signal does not promise lossless delivery or
recover every intermediate historical state.
