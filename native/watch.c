/* Choose one MIME from each immutable data-control offer before receiving it. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#include <wayland-client.h>
#include "data-control-client.h"

static struct wl_display *display;
static struct wl_seat *seat;
static struct zwlr_data_control_manager_v1 *manager;
static char **types, **command;
static int type_count;
static bool finished;

struct offer {
    struct zwlr_data_control_offer_v1 *proxy;
    const char *mime;
    int priority;
    bool sensitive;
};

static void destroy_offer(struct offer *offer) {
    zwlr_data_control_offer_v1_destroy(offer->proxy);
    free(offer);
}

static void offered_type(void *data, struct zwlr_data_control_offer_v1 *proxy,
                         const char *mime) {
    struct offer *offer = data;
    if (strcmp(mime, "x-kde-passwordManagerHint") == 0)
        offer->sensitive = true;
    for (int i = 0; i < offer->priority; ++i) {
        if (strcmp(types[i], mime) == 0) {
            offer->mime = types[i];
            offer->priority = i;
            break;
        }
    }
}

static const struct zwlr_data_control_offer_v1_listener offer_listener = {
    .offer = offered_type,
};

static void data_offer(void *data, struct zwlr_data_control_device_v1 *device,
                       struct zwlr_data_control_offer_v1 *proxy) {
    struct offer *offer = calloc(1, sizeof(*offer));
    if (!offer) {
        perror("clipboard offer allocation");
        exit(1);
    }
    offer->proxy = proxy;
    offer->priority = type_count;
    zwlr_data_control_offer_v1_add_listener(proxy, &offer_listener, offer);
}

static void selection(void *data, struct zwlr_data_control_device_v1 *device,
                      struct zwlr_data_control_offer_v1 *proxy) {
    if (!proxy)
        return;
    struct offer *offer = zwlr_data_control_offer_v1_get_user_data(proxy);
    if (!offer->mime || offer->sensitive) {
        destroy_offer(offer);
        return;
    }
    int pipefd[2];
    if (pipe(pipefd) < 0) {
        perror("clipboard pipe");
        destroy_offer(offer);
        return;
    }
    zwlr_data_control_offer_v1_receive(proxy, offer->mime, pipefd[1]);
    if (wl_display_flush(display) < 0) {
        perror("clipboard receive");
        close(pipefd[0]);
        close(pipefd[1]);
        destroy_offer(offer);
        finished = true;
        return;
    }
    close(pipefd[1]);
    pid_t child = fork();
    if (child == 0) {
        if (dup2(pipefd[0], STDIN_FILENO) < 0 ||
            setenv("CLIPBOARD_STATE", "data", 1) < 0 ||
            setenv("CLIPBOARD_TYPE", offer->mime, 1) < 0) {
            perror("clipboard capture setup");
            _exit(1);
        }
        close(pipefd[0]);
        execvp(command[0], command);
        perror("clipboard capture command");
        _exit(1);
    }
    close(pipefd[0]);
    if (child < 0) {
        perror("clipboard capture fork");
        finished = true;
    } else {
        int status;
        while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
    }
    destroy_offer(offer);
}

static void primary_selection(void *data, struct zwlr_data_control_device_v1 *device,
                              struct zwlr_data_control_offer_v1 *proxy) {
    if (proxy)
        destroy_offer(zwlr_data_control_offer_v1_get_user_data(proxy));
}

static void device_finished(void *data, struct zwlr_data_control_device_v1 *device) {
    finished = true;
}

static const struct zwlr_data_control_device_v1_listener device_listener = {
    .data_offer = data_offer,
    .selection = selection,
    .primary_selection = primary_selection,
    .finished = device_finished,
};

static void capabilities(void *data, struct wl_seat *proxy, uint32_t capabilities) {}
static const struct wl_seat_listener seat_listener = {.capabilities = capabilities};

static void global(void *data, struct wl_registry *registry, uint32_t name,
                   const char *interface, uint32_t version) {
    if (!seat && strcmp(interface, wl_seat_interface.name) == 0) {
        seat = wl_registry_bind(registry, name, &wl_seat_interface, 1);
        wl_seat_add_listener(seat, &seat_listener, NULL);
    }
    if (!manager && strcmp(interface, zwlr_data_control_manager_v1_interface.name) == 0)
        manager = wl_registry_bind(registry, name,
                                   &zwlr_data_control_manager_v1_interface,
                                   version < 2 ? version : 2);
}

static void removed(void *data, struct wl_registry *registry, uint32_t name) {}
static const struct wl_registry_listener registry_listener = {
    .global = global,
    .global_remove = removed,
};

int main(int argc, char **argv) {
    int separator = 1;
    while (separator < argc && strcmp(argv[separator], "--") != 0)
        ++separator;
    if (separator == 1 || separator + 1 >= argc) {
        fprintf(stderr, "Usage: %s MIME... -- COMMAND...\n", argv[0]);
        return 1;
    }
    types = argv + 1;
    type_count = separator - 1;
    command = argv + separator + 1;
    display = wl_display_connect(NULL);
    if (!display) {
        fprintf(stderr, "Could not connect to Wayland\n");
        return 1;
    }
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, NULL);
    if (wl_display_roundtrip(display) < 0 || !manager || !seat) {
        fprintf(stderr, "Clipboard capture requires wlr data-control and a Wayland seat\n");
        wl_display_disconnect(display);
        return 1;
    }
    struct zwlr_data_control_device_v1 *device =
        zwlr_data_control_manager_v1_get_data_device(manager, seat);
    zwlr_data_control_device_v1_add_listener(device, &device_listener, NULL);
    while (!finished && wl_display_dispatch(display) >= 0) {}
    fprintf(stderr, "Clipboard data-control connection closed\n");
    wl_display_disconnect(display);
    return 1;
}
