import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
    pickContactDisplayName,
    pickContactUsername,
} from '../src/httpService.ts';

test('contact username resolution accepts common WeChat contact field names', () => {
    assert.equal(pickContactUsername({ username: 'friend_wxid' }), 'friend_wxid');
    assert.equal(pickContactUsername({ user_name: 'friend_wxid' }), 'friend_wxid');
    assert.equal(pickContactUsername({ userName: 'friend_wxid' }), 'friend_wxid');
    assert.equal(pickContactUsername({ wxid: 'friend_wxid' }), 'friend_wxid');
});

test('contact display names prefer resolved map, remark, nickname, alias, then username', () => {
    assert.equal(
        pickContactDisplayName({ username: 'friend_wxid', remark: '备注', nick_name: 'FriendName' }, { friend_wxid: 'FriendName' }),
        'FriendName'
    );
    assert.equal(pickContactDisplayName({ username: 'friend_wxid', remark: '备注' }, {}), '备注');
    assert.equal(pickContactDisplayName({ username: 'friend_wxid', nickName: 'FriendName' }, {}), 'FriendName');
    assert.equal(pickContactDisplayName({ username: 'friend_wxid', alias: 'friend_wxid' }, {}), 'friend_wxid');
    assert.equal(pickContactDisplayName({ username: 'friend_wxid' }, {}), 'friend_wxid');
});

test('HTTP service exposes a single-message lookup endpoint for quoted message resolution', () => {
    const source = readFileSync(new URL('../src/httpService.ts', import.meta.url), 'utf8');

    assert.ok(source.includes("pathname === '/api/v1/message'"));
    assert.ok(source.includes('getMessageByServerId(talker, serverId)'));
});
