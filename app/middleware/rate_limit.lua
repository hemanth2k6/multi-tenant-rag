--[[
Atomic sliding-window rate limiter using a Redis sorted set.

KEYS[1]  = rate-limit key, e.g. "rl:{tenant_id}"
ARGV[1]  = current epoch time in milliseconds (string)
ARGV[2]  = window size in milliseconds (string), e.g. "60000"
ARGV[3]  = request limit within the window (string), e.g. "10"

Returns a three-element array:
  {allowed, current_count, limit}
  allowed = 1 if the request is permitted, 0 if denied.
]]

local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])

-- Remove all members outside the current sliding window
redis.call("ZREMRANGEBYSCORE", key, 0, now - window)

-- Count requests currently in the window
local count = redis.call("ZCARD", key)

if count >= limit then
    -- Denied — return without adding a new entry
    return {0, count, limit}
end

-- Allowed — record this request using timestamp as score
-- Use a unique member sequence to avoid collisions when multiple requests arrive in the same ms
local member = now .. ":" .. redis.call("INCR", key .. ":seq")
redis.call("ZADD", key, now, member)

-- Set TTL so key automatically expires after the window passes
redis.call("PEXPIRE", key, window)

return {1, count + 1, limit}
