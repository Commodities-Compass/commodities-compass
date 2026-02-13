FROM node:18-alpine as builder

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

# Accept build arguments from Railway
ARG AUTH0_DOMAIN
ARG AUTH0_CLIENT_ID
ARG AUTH0_API_AUDIENCE
ARG AUTH0_REDIRECT_URI
ARG API_BASE_URL
ARG AUTH0_ISSUER

# Set environment variables for the build
ENV AUTH0_DOMAIN=$AUTH0_DOMAIN
ENV AUTH0_CLIENT_ID=$AUTH0_CLIENT_ID
ENV AUTH0_API_AUDIENCE=$AUTH0_API_AUDIENCE
ENV AUTH0_REDIRECT_URI=$AUTH0_REDIRECT_URI
ENV API_BASE_URL=$API_BASE_URL
ENV AUTH0_ISSUER=$AUTH0_ISSUER

# Build the application
RUN pnpm run build

# Production stage
FROM node:18-alpine

WORKDIR /app

# Install serve globally
RUN npm install -g serve

# Copy built application from builder stage
COPY --from=builder /app/dist ./dist

# Expose port
EXPOSE 3000

# Start the application - listen on all interfaces for Railway
CMD ["sh", "-c", "serve -s dist -l tcp://0.0.0.0:${PORT:-3000}"]
