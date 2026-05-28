import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

import {
    buildLaunchPlan,
    shouldRefreshRuntimeFile,
} from '../scripts/weflow-host.mjs';

function normalizePath(path: string): string {
    return path.replace(/\\/g, '/');
}

test('package dev script uses the WCDB-compatible host launcher', () => {
    const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));

    assert.equal(packageJson.scripts.dev, 'node scripts/weflow-host.mjs dev');
    assert.equal(packageJson.scripts.start, 'node scripts/weflow-host.mjs start');
});

test('windows dev mode launches tsx through a whitelisted weflow.exe host', () => {
    const cwd = 'C:/app/weflow-api-cli';
    const plan = buildLaunchPlan({
        mode: 'dev',
        cwd,
        platform: 'win32',
        processExecPath: 'C:/Program Files/nodejs/node.exe',
        tsxCliPath: join(cwd, 'node_modules/tsx/dist/cli.mjs'),
    });

    assert.equal(normalizePath(plan.command), 'C:/app/weflow-api-cli/.runtime/weflow.exe');
    assert.deepEqual(plan.args.map(normalizePath), [
        'C:/app/weflow-api-cli/node_modules/tsx/dist/cli.mjs',
        'src/index.ts',
    ]);
    assert.equal(plan.hosted, true);
    assert.equal(plan.runtimeSource, 'C:/Program Files/nodejs/node.exe');
    assert.equal(normalizePath(plan.runtimeDir), 'C:/app/weflow-api-cli/.runtime');
});

test('start mode launches the compiled entry through the same windows host', () => {
    const cwd = 'C:/app/weflow-api-cli';
    const plan = buildLaunchPlan({
        mode: 'start',
        cwd,
        platform: 'win32',
        processExecPath: 'C:/Program Files/nodejs/node.exe',
    });

    assert.equal(normalizePath(plan.command), 'C:/app/weflow-api-cli/.runtime/weflow.exe');
    assert.deepEqual(plan.args.map(normalizePath), ['C:/app/weflow-api-cli/dist/index.js']);
    assert.equal(plan.hosted, true);
});

test('non-windows dev mode keeps the current node executable and local tsx CLI', () => {
    const cwd = '/repo/weflow-api-cli';
    const plan = buildLaunchPlan({
        mode: 'dev',
        cwd,
        platform: 'darwin',
        processExecPath: '/usr/local/bin/node',
        tsxCliPath: join(cwd, 'node_modules/tsx/dist/cli.mjs'),
    });

    assert.equal(plan.command, '/usr/local/bin/node');
    assert.deepEqual(plan.args, [join(cwd, 'node_modules/tsx/dist/cli.mjs'), 'src/index.ts']);
    assert.equal(plan.hosted, false);
});

test('runtime host file refreshes when target is missing or size changed', () => {
    assert.equal(shouldRefreshRuntimeFile({ sourceSize: 100, targetExists: false }), true);
    assert.equal(shouldRefreshRuntimeFile({ sourceSize: 100, targetExists: true, targetSize: 99 }), true);
    assert.equal(shouldRefreshRuntimeFile({ sourceSize: 100, targetExists: true, targetSize: 100 }), false);
});
