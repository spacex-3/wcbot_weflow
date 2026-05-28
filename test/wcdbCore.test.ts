import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
    buildDllSearchPaths,
    buildProtectionResourceCandidates,
    buildWcdbDllCandidates,
    shouldNotifyMonitorUnavailable,
    shouldRestartMonitorAfterClose,
    WcdbCore,
} from '../src/wcdbCore.ts';

function normalizePath(path: string): string {
    return path.replace(/\\/g, '/');
}

test('prefers the upstream wcdb platform resource layout before legacy flat DLLs', () => {
    const candidates = buildWcdbDllCandidates({
        resourcesPath: 'C:/app/resources',
        cwd: 'C:/app',
        platform: 'win32',
        arch: 'x64',
        env: {},
    }).map(normalizePath);

    assert.equal(candidates[0], 'C:/app/resources/wcdb/win32/x64/wcdb_api.dll');
    assert.ok(candidates.includes('C:/app/resources/wcdb_api.dll'));
});

test('keeps WCDB_DLL_PATH as the first DLL candidate', () => {
    const candidates = buildWcdbDllCandidates({
        resourcesPath: 'C:/app/resources',
        cwd: 'C:/app',
        platform: 'win32',
        arch: 'x64',
        env: { WCDB_DLL_PATH: 'D:/custom/wcdb_api.dll' },
    }).map(normalizePath);

    assert.equal(candidates[0], 'D:/custom/wcdb_api.dll');
});

test('builds unique InitProtection resource candidates from DLL location outward', () => {
    const candidates = buildProtectionResourceCandidates({
        dllPath: 'C:/app/resources/wcdb/win32/x64/wcdb_api.dll',
        resourcesPath: 'C:/app/resources',
        cwd: 'C:/app',
        processResourcesPath: 'C:/pkg',
    }).map(normalizePath);

    assert.equal(candidates[0], 'C:/app/resources/wcdb/win32/x64');
    assert.equal(candidates[1], 'C:/app/resources/wcdb/win32');
    assert.ok(candidates.includes('C:/pkg'));
    assert.ok(candidates.includes('C:/pkg/resources'));
    assert.ok(candidates.includes('C:/app/resources'));
    assert.equal(new Set(candidates).size, candidates.length);
});

test('builds DLL search paths that prioritize the local WCDB runtime directories', () => {
    const paths = buildDllSearchPaths({
        dllPath: 'C:/app/resources/wcdb/win32/x64/wcdb_api.dll',
        resourcesPath: 'C:/app/resources',
        cwd: 'C:/app',
        platform: 'win32',
        arch: 'x64',
    }).map(normalizePath);

    assert.deepEqual(paths.slice(0, 4), [
        'C:/app/resources/wcdb/win32/x64',
        'C:/app/resources',
        'C:/app/resources/runtime/win32',
        'C:/app/resources/key/win32/x64',
    ]);
}
);

test('ships the upstream nested Windows x64 WCDB resource layout', () => {
    const root = new URL('../resources/', import.meta.url);

    assert.ok(existsSync(new URL('wcdb/win32/x64/wcdb_api.dll', root)));
    assert.ok(existsSync(new URL('wcdb/win32/x64/WCDB.dll', root)));
    assert.ok(existsSync(new URL('wcdb/win32/x64/SDL2.dll', root)));
    assert.ok(existsSync(new URL('runtime/win32/vcruntime140.dll', root)));
    assert.ok(existsSync(new URL('key/win32/x64/wx_key.dll', root)));
});

test('initialization source runs InitProtection before wcdb_init', () => {
    const source = readFileSync(new URL('../src/wcdbCore.ts', import.meta.url), 'utf8');
    const protectionIndex = source.indexOf("InitProtection(const char* resourcePath)");
    const initIndex = source.indexOf("wcdb_init()");

    assert.ok(protectionIndex >= 0, 'InitProtection binding is missing');
    assert.ok(initIndex >= 0, 'wcdb_init binding is missing');
    assert.ok(protectionIndex < initIndex, 'InitProtection must be bound before wcdb_init');
});

test('initialization source dumps DLL diagnostics when wcdb_init fails', () => {
    const source = readFileSync(new URL('../src/wcdbCore.ts', import.meta.url), 'utf8');

    assert.ok(source.includes('this.logDllDiagnostics(`wcdb_init failed'), 'wcdb_init failures should dump DLL diagnostics');
});

test('binds optional WCDB message lookup by server id for quoted replies', () => {
    const source = readFileSync(new URL('../src/wcdbCore.ts', import.meta.url), 'utf8');

    assert.ok(source.includes('wcdb_get_message_by_svrid'), 'server id lookup binding is missing');
    assert.ok(source.includes('getMessageByServerId(sessionId: string, serverId: string)'), 'public lookup method is missing');
});

test('reads the dynamic monitor pipe name exposed by the WCDB DLL', () => {
    const core = Object.create(WcdbCore.prototype) as any;
    let freedPtr: unknown = null;

    core.wcdbGetMonitorPipeName = (outPtr: any[]) => {
        outPtr[0] = 'pipe-name-ptr';
        return 0;
    };
    core.koffi = {
        decode: (ptr: unknown) => {
            assert.equal(ptr, 'pipe-name-ptr');
            return '\\\\.\\pipe\\weflow_monitor_1234';
        },
    };
    core.wcdbFreeString = (ptr: unknown) => {
        freedPtr = ptr;
    };

    assert.equal(core.getMonitorPipePath(), '\\\\.\\pipe\\weflow_monitor_1234');
    assert.equal(freedPtr, 'pipe-name-ptr');
});

test('falls back to the legacy monitor pipe name when the DLL does not expose one', () => {
    const core = Object.create(WcdbCore.prototype) as any;

    core.wcdbGetMonitorPipeName = null;

    assert.equal(core.getMonitorPipePath(), '\\\\.\\pipe\\weflow_monitor');
});

test('does not restart the pipe server after an unconnected client closes from an error', () => {
    assert.equal(shouldRestartMonitorAfterClose({
        hadError: true,
        hasCallback: true,
        isStopping: false,
        wasConnected: false,
    }), false);

    assert.equal(shouldRestartMonitorAfterClose({
        hadError: false,
        hasCallback: true,
        isStopping: false,
        wasConnected: true,
    }), true);
});

test('notifies fallback once monitor pipe connection retries are exhausted', () => {
    assert.equal(shouldNotifyMonitorUnavailable({ retryCount: 4, maxRetries: 5 }), false);
    assert.equal(shouldNotifyMonitorUnavailable({ retryCount: 5, maxRetries: 5 }), true);
});
