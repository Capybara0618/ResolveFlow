CREATE TABLE account_notification_read (
    username VARCHAR(120) NOT NULL,
    notification_id VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    read_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY(username,notification_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Historical tickets keep an unknown creation time; no invented timestamps/backfill notifications.
ALTER TABLE support_ticket ADD COLUMN created_at TIMESTAMP(6) NULL;
CREATE INDEX ix_support_message_recipient ON support_message(author,recipient,created_at,message_id);
CREATE INDEX ix_support_ticket_created ON support_ticket(merchant_id,created_at,ticket_id);
CREATE INDEX ix_case_notice_kind ON case_timeline(kind,occurred_at,event_id);
