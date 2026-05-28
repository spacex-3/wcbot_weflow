#!/usr/bin/env node
import { spawn } from 'node:child_process';
import {
    copyFileSync,
    existsSync,
    mkdirSync,
    readdirSync,
    statSync,
} from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HOST_EXE_NAME = 'weflow.exe';
const DEFAULT_MODE = 'dev';

export function findLocalTsxCli(cwd = process.cwd()) {
    const candidates = [
        join(cwd, 'node_modules', 'tsx', 'dist', 'cli.mjs'),
        join(cwd, 'node_modules', 'tsx', 'dist', 'cli.cjs'),
    ];

    for (const candidate of candidates) {
        if (existsSync(candidate)) return candidate;
    }

    return candidates[0];
}

export function buildLaunchPlan(options = {}) {
    const cwd = options.cwd || process.cwd();
    const mode = options.mode || DEFAULT_MODE;
    const platform = options.platform || process.platform;
    const processExecPath = options.processExecPath || process.execPath;
    const runtimeDir = join(cwd, '.runtime');
    const windowsHostPath = join(runtimeDir, HOST_EXE_NAME);
    const command = platform === 'win32' ? windowsHostPath : processExecPath;

    if (mode === 'start') {
        return {
            mode,
            command,
            args: [join(cwd, 'dist', 'index.js')],
            hosted: platform === 'win32',
            runtimeDir,
            runtimeSource: processExecPath,
        };
    }

    if (mode !== 'dev') {
        throw new Error(`Unsupported launch mode: ${mode}`);
    }

    const tsxCliPath = options.tsxCliPath || findLocalTsxCli(cwd);

    return {
        mode,
        command,
        args: [tsxCliPath, 'src/index.ts'],
        hosted: platform === 'win32',
        runtimeDir,
        runtimeSource: processExecPath,
    };
}

export function shouldRefreshRuntimeFile(options) {
    if (!options.targetExists) return true;
    return options.sourceSize !== options.targetSize;
}

function copyIfNeeded(sourcePath, targetPath) {
    const sourceStat = statSync(sourcePath);
    const targetExists = existsSync(targetPath);
    const targetSize = targetExists ? statSync(targetPath).size : undefined;

    if (!shouldRefreshRuntimeFile({
        sourceSize: sourceStat.size,
        targetExists,
        targetSize,
    })) {
        return false;
    }

    copyFileSync(sourcePath, targetPath);
    return true;
}

function copyWindowsHostRuntime(plan) {
    mkdirSync(plan.runtimeDir, { recursive: true });
    copyIfNeeded(plan.runtimeSource, plan.command);

    const nodeDir = dirname(plan.runtimeSource);
    for (const entry of readdirSync(nodeDir)) {
        if (!entry.toLowerCase().endsWith('.dll')) continue;

        const sourcePath = join(nodeDir, entry);
        const targetPath = join(plan.runtimeDir, entry);
        copyIfNeeded(sourcePath, targetPath);
    }
}

function ensureLaunchPlanReady(plan) {
    if (plan.mode === 'dev' && !existsSync(plan.args[0])) {
        throw new Error(`Cannot find local tsx CLI at ${plan.args[0]}. Run npm install first.`);
    }

    if (plan.mode === 'start' && !existsSync(plan.args[0])) {
        throw new Error(`Cannot find built entry at ${plan.args[0]}. Run npm run build first.`);
    }

    if (plan.hosted) {
        copyWindowsHostRuntime(plan);
    }
}

export function run(mode = DEFAULT_MODE) {
    const plan = buildLaunchPlan({ mode });
    ensureLaunchPlanReady(plan);

    if (plan.hosted) {
        console.log(`Using ${basename(plan.command)} as the WCDB host process.`);
    }

    const child = spawn(plan.command, plan.args, {
        cwd: process.cwd(),
        env: {
            ...process.env,
            WEFLOW_API_CLI_HOSTED: plan.hosted ? '1' : process.env.WEFLOW_API_CLI_HOSTED,
        },
        stdio: 'inherit',
        windowsHide: false,
    });

    child.on('error', (error) => {
        console.error(error.message);
        process.exitCode = 1;
    });

    child.on('exit', (code, signal) => {
        if (signal) {
            process.kill(process.pid, signal);
            return;
        }
        process.exit(code ?? 0);
    });
}

const invokedUrl = process.argv[1] ? pathToFileURL(process.argv[1]).href : '';
if (invokedUrl === pathToFileURL(fileURLToPath(import.meta.url)).href) {
    run(process.argv[2] || DEFAULT_MODE);
}
