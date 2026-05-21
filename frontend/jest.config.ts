import type { Config } from "jest";

const config: Config = {
  testEnvironment: "jsdom",
  moduleNameMapper: {
    "\\.(css|less|scss)$": "<rootDir>/__mocks__/styleMock.js",
  },
  transform: {
    "^.+\\.tsx?$": [
      "ts-jest",
      {
        tsconfig: {
          jsx: "react-jsx",
          esModuleInterop: true,
          module: "commonjs",
          target: "es2020",
          types: ["jest", "node", "@testing-library/jest-dom"],
          lib: ["dom", "es2020"],
        },
      },
    ],
  },
  collectCoverageFrom: ["src/**/*.{ts,tsx}", "!src/main.tsx", "!src/types.ts"],
  testMatch: ["<rootDir>/tests/**/*.test.{ts,tsx}"],
};

export default config;
