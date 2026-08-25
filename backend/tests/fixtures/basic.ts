import { readFile } from "node:fs";
import type { User } from "./types";

interface Config {
    port: number;
}

const DEFAULT_PORT = 3000;

type Cast<T> = T;
const wrapped = ((input: string) => input.trim()) as Cast<(s: string) => string>;

export const parse = (input: string): string[] => {
    return input.split(",");
};

export function readConfig(path: string): Config {
    return JSON.parse(readFile(path, "utf8"));
}

export class Server {
    private port: number;

    constructor(port: number) {
        this.port = port;
    }

    start(): void {
        console.log(`listening on ${this.port}`);
    }
}
