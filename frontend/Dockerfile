FROM node:22-alpine as builder

# Set working directory
WORKDIR /app

# Install pnpm via corepack
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

# Copy package files and lock file
COPY package.json pnpm-lock.yaml ./

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy source code
COPY . .

# Accept build arguments
ARG AUTH0_DOMAIN
ARG AUTH0_CLIENT_ID
ARG AUTH0_API_AUDIENCE
ARG AUTH0_REDIRECT_URI
ARG API_BASE_URL
ARG AUTH0_ISSUER
ARG SENTRY_DSN
ARG GIT_COMMIT_SHA
ARG SENTRY_AUTH_TOKEN
ARG ENVIRONMENT=production
# Feature flag — exposes the FR/EN language switcher in the masthead. Defaults
# OFF so an unset build arg can never accidentally ship the EN edition; flip via
# the GitHub repo variable of the same name (no code change needed).
ARG VITE_FEATURE_LANG_SWITCHER=false

# Set environment variables for the build
ENV AUTH0_DOMAIN=$AUTH0_DOMAIN
ENV AUTH0_CLIENT_ID=$AUTH0_CLIENT_ID
ENV AUTH0_API_AUDIENCE=$AUTH0_API_AUDIENCE
ENV AUTH0_REDIRECT_URI=$AUTH0_REDIRECT_URI
ENV API_BASE_URL=$API_BASE_URL
ENV AUTH0_ISSUER=$AUTH0_ISSUER
ENV SENTRY_DSN=$SENTRY_DSN
ENV GIT_COMMIT_SHA=$GIT_COMMIT_SHA
ENV SENTRY_AUTH_TOKEN=$SENTRY_AUTH_TOKEN
ENV ENVIRONMENT=$ENVIRONMENT
ENV VITE_FEATURE_LANG_SWITCHER=$VITE_FEATURE_LANG_SWITCHER

# Build the application (sentry-vite-plugin uploads source maps then deletes the .map files
# from dist, so the final image never ships them. SENTRY_AUTH_TOKEN is also never carried
# over to the runtime stage below — it stays scoped to this build stage.)
RUN pnpm run build

# Production stage
FROM node:22-alpine

WORKDIR /app

# Install serve globally
RUN npm install -g serve

# Copy built application from builder stage
COPY --from=builder /app/dist ./dist

# Expose port
EXPOSE 3000

# Start the application - listen on all interfaces for Railway
CMD ["sh", "-c", "serve -s dist -l tcp://0.0.0.0:${PORT:-3000}"]
