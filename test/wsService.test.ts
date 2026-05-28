import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
    buildNewMessageNotification,
    resolveDisplayName,
} from '../src/wsService.ts';

test('resolveDisplayName prefers display name maps over raw usernames', () => {
    assert.equal(resolveDisplayName('fantasysk', { fantasysk: 'Kayson' }), 'Kayson');
    assert.equal(resolveDisplayName('fantasysk', {}), 'fantasysk');
    assert.equal(resolveDisplayName('', { fantasysk: 'Kayson' }), '');
});

test('new message notifications keep sender id and include sender display name', () => {
    const notification = buildNewMessageNotification({
        sessionId: 'fantasysk',
        sender: 'fantasysk',
        senderName: 'Kayson',
        timestamp: 1779923259,
        type: 0,
        content: '你好',
        platformMessageId: '2026828130733625346',
        now: 1779894420937,
    });

    assert.deepEqual(notification, {
        type: 'new_message',
        sessionId: 'fantasysk',
        message: {
            sender: 'fantasysk',
            senderName: 'Kayson',
            senderDisplayName: 'Kayson',
            timestamp: 1779923259,
            type: 0,
            content: '你好',
            referencedPlatformMessageId: undefined,
            url: undefined,
            platformMessageId: '2026828130733625346',
        },
        timestamp: 1779894420937,
    });
});
