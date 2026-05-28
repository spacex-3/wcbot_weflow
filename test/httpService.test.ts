import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
    pickContactDisplayName,
    pickContactUsername,
} from '../src/httpService.ts';

test('contact username resolution accepts common WeChat contact field names', () => {
    assert.equal(pickContactUsername({ username: 'fantasysk' }), 'fantasysk');
    assert.equal(pickContactUsername({ user_name: 'fantasysk' }), 'fantasysk');
    assert.equal(pickContactUsername({ userName: 'fantasysk' }), 'fantasysk');
    assert.equal(pickContactUsername({ wxid: 'fantasysk' }), 'fantasysk');
});

test('contact display names prefer resolved map, remark, nickname, alias, then username', () => {
    assert.equal(
        pickContactDisplayName({ username: 'fantasysk', remark: '备注', nick_name: 'Kayson' }, { fantasysk: 'Kayson' }),
        'Kayson'
    );
    assert.equal(pickContactDisplayName({ username: 'fantasysk', remark: '备注' }, {}), '备注');
    assert.equal(pickContactDisplayName({ username: 'fantasysk', nickName: 'Kayson' }, {}), 'Kayson');
    assert.equal(pickContactDisplayName({ username: 'fantasysk', alias: 'fantasysk' }, {}), 'fantasysk');
    assert.equal(pickContactDisplayName({ username: 'fantasysk' }, {}), 'fantasysk');
});

test('HTTP service exposes a single-message lookup endpoint for quoted message resolution', () => {
    const source = readFileSync(new URL('../src/httpService.ts', import.meta.url), 'utf8');

    assert.ok(source.includes("pathname === '/api/v1/message'"));
    assert.ok(source.includes('getMessageByServerId(talker, serverId)'));
});
